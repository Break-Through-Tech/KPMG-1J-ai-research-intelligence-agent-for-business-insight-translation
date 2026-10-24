# unit tests for src/rag/lance_retriever.py
# builds a tiny LanceDB index with the real embedding model, like tests/test_indexing.py

import pandas as pd
import pytest

from src.indexing.store import open_index, update_index, update_paper_vectors
from src.pipeline.pipeline import answer_query, format_retrieved_content
from src.rag.lance_retriever import LanceCombinedRetriever, LanceRetriever, rrf_merge
from src.vectorizing.embedder import TextEmbedder

# paper id -> (title, abstract, [(section, section_type, text), ...])
PAPERS = {
    "2609.00001": ("Retrieval Augmented Generation for Audits",
                   "We retrieve passages from financial filings before generating an answer.",
                   [("Abstract", "abstract",
                     "We retrieve passages from financial filings before generating an answer."),
                    ("1 Introduction", "introduction", "Auditors need answers grounded in financial filings."),
                    ("4 Results", "results",
                     "Retrieval augmented generation reduced unsupported claims in audit reports."),
                    ("6 Limitations", "limitations", "We only tested filings written in English.")]),
    "2609.00002": ("Robot Grasping with Tactile Sensors",
                   "A gripper uses touch sensors to pick up fragile objects.",
                   [("1 Introduction", "introduction", "Tactile sensors measure contact force on each finger."),
                    ("4 Results", "results", "The gripper picked up eggs without breaking them.")]),
    "2609.00003": ("Parameter Efficient Fine Tuning",
                   "We study the zorblax adapter, a low rank method for tuning large models.",
                   [("1 Introduction", "introduction", "Low rank adapters update a small number of weights."),
                    ("4 Results", "results", "The zorblax adapter matched full fine tuning on reading tasks."),
                    ("5 Conclusion", "conclusion", "Adapters are a cheap way to tune large models.")]),
}

# what the pipeline reads from each result
PIPELINE_KEYS = {"paper_id", "title", "abstract", "score", "chunk_id",
                 "best_chunk_section", "best_chunk_text", "passages"}


def texts_of(paper_id):
    return [text for _, _, text in PAPERS[paper_id][2]]


def make_chunks():
    rows = []
    for paper_id, (title, _, sections) in PAPERS.items():
        for i, (section, section_type, text) in enumerate(sections):
            rows.append({
                "chunk_id": f"{paper_id}::{i:04d}", "paper_id": paper_id, "version": 1, "chunk_index": i,
                "title": title, "authors": ["Jane Doe"], "arxiv_url": f"http://arxiv.org/abs/{paper_id}v1",
                "section": section, "section_type": section_type,
                "published_date": "2026-09-01", "primary_category": "cs.AI", "categories": ["cs.AI"],
                "text": text, "text_for_embedding": f"{title}\nSection: {section}\n\n{text}",
            })
    return pd.DataFrame(rows)


def make_papers():
    return pd.DataFrame([
        {"arxiv_id": f"{paper_id}v1", "base_id": paper_id, "version": 1,
         "title": title, "abstract_clean": abstract}
        for paper_id, (title, abstract, _) in PAPERS.items()
    ])


def build_index(folder, embedder, paper_vectors=True):
    index_dir = folder / "index"
    table = open_index(index_dir, embedder)
    update_index(table, make_chunks(), embedder, index_dir)
    if paper_vectors:
        update_paper_vectors(index_dir, table, make_papers(), embedder)

    papers_path = folder / "papers_clean.parquet"
    make_papers()[["arxiv_id", "title", "abstract_clean"]].to_parquet(papers_path)

    return str(papers_path), str(index_dir)


class FakeLLM:

    def generate(self, system_prompt, user_prompt):
        return "Key Findings: grounded answers. [2609.00001v1]"


@pytest.fixture(scope="module")
def embedder():
    return TextEmbedder()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory, embedder):
    return build_index(tmp_path_factory.mktemp("lance"), embedder)


@pytest.fixture(scope="module", params=[LanceRetriever, LanceCombinedRetriever])
def retriever(request, corpus, embedder):
    papers_path, index_dir = corpus
    return request.param(papers_path=papers_path, index_dir=index_dir, embedder=embedder)


def test_rrf_merge_ranks_papers_found_twice_first():
    ranking, scores = rrf_merge([["a", "b"], ["c", "b"]], k=60)

    assert ranking[0] == "b"
    assert scores["b"] == pytest.approx(2 / 62)


def test_one_result_per_paper_and_top_k_respected(retriever):
    results = retriever.search("financial audit answers", top_k=2)

    assert len(results) == 2
    assert len({r["paper_id"] for r in results}) == 2


def test_results_have_the_fields_the_pipeline_needs(retriever):
    result = retriever.search("financial audit answers", top_k=1)[0]

    assert PIPELINE_KEYS <= set(result)
    assert result["paper_id"] == "2609.00001v1"
    assert result["abstract"] == PAPERS["2609.00001"][1]
    assert result["best_chunk_text"] in texts_of("2609.00001")


def test_main_evidence_is_never_the_abstract_chunk(retriever):
    # the abstract chunk matches this query best, but the LLM already gets the abstract
    result = retriever.search(PAPERS["2609.00001"][1], top_k=1)[0]

    assert result["paper_id"] == "2609.00001v1"
    assert result["best_chunk_section"] != "Abstract"


def test_papers_come_with_results_and_limitations_passages(retriever):
    result = retriever.search("financial audit answers", top_k=1)[0]

    passages = {p["label"]: p for p in result["passages"]}
    assert passages["results"]["section_type"] == "results"
    assert passages["limitations"]["text"] == "We only tested filings written in English."
    # no passage repeats the main evidence
    assert result["chunk_id"] not in {p["chunk_id"] for p in result["passages"]}


def test_conclusion_stands_in_when_a_paper_has_no_limitations_section(retriever):
    result = retriever.search("zorblax", top_k=1)[0]

    limitations = [p for p in result["passages"] if p["label"] == "limitations"]
    assert limitations[0]["section_type"] == "conclusion"


def test_papers_without_those_sections_get_fewer_passages(retriever):
    result = retriever.search("gripper tactile sensors", top_k=1)[0]

    assert result["paper_id"] == "2609.00002v1"
    assert all(p["label"] != "limitations" for p in result["passages"])


def test_passages_reach_the_summarization_prompt(retriever):
    content = format_retrieved_content(retriever.search("financial audit answers", top_k=1))

    assert "Limitations passage (Section: 6 Limitations" in content
    assert "We only tested filings written in English." in content


def test_conclusion_passage_is_not_called_limitations_in_the_prompt(retriever):
    content = format_retrieved_content(retriever.search("zorblax", top_k=1))

    assert "Conclusion passage (Section: 5 Conclusion" in content
    assert "Limitations passage" not in content


def test_passages_can_be_turned_off(corpus, embedder):
    papers_path, index_dir = corpus
    retriever = LanceRetriever(papers_path=papers_path, index_dir=index_dir,
                               embedder=embedder, passages=False)

    assert retriever.search("financial audit answers", top_k=1)[0]["passages"] == []


def test_paper_vectors_are_read_from_the_index(corpus, embedder, monkeypatch):
    papers_path, index_dir = corpus

    def fail(texts):
        raise AssertionError("paper vectors should come from the index, not be embedded again")

    monkeypatch.setattr(embedder, "embed_documents", fail)
    LanceCombinedRetriever(papers_path=papers_path, index_dir=index_dir, embedder=embedder)


def test_index_without_paper_vectors_ranks_the_same(corpus, embedder, tmp_path):
    # an index built before paper vectors were stored still works: the retriever embeds them itself
    stored = LanceCombinedRetriever(papers_path=corpus[0], index_dir=corpus[1], embedder=embedder)
    papers_path, index_dir = build_index(tmp_path, embedder, paper_vectors=False)
    fresh = LanceCombinedRetriever(papers_path=papers_path, index_dir=index_dir, embedder=embedder)

    assert stored.paper_ids == fresh.paper_ids
    assert stored.paper_vectors == pytest.approx(fresh.paper_vectors, abs=1e-5)


def test_keyword_match_finds_exact_names(retriever):
    # "zorblax" is a made-up word, so only keyword search can match it exactly
    assert retriever.search("zorblax", top_k=1)[0]["paper_id"] == "2609.00003v1"


def test_answer_query_runs_with_lance_retrievers(retriever):
    result = answer_query("How are audits using retrieval?", retriever, FakeLLM(), top_k=2)

    assert result["citation_check"]["cited_not_retrieved"] == []
    assert result["sources"][0]["arxiv_url"] == "https://arxiv.org/abs/2609.00001"


def test_empty_query_and_bad_top_k_are_rejected(retriever):
    with pytest.raises(ValueError):
        retriever.search("   ")
    with pytest.raises(ValueError):
        retriever.search("audits", top_k=0)


def test_refuses_corpus_missing_indexed_papers(corpus, embedder, tmp_path):
    _, index_dir = corpus
    papers_path = tmp_path / "papers_clean.parquet"
    pd.DataFrame([{"arxiv_id": "2609.00001v1", "title": "t", "abstract_clean": "a"}]).to_parquet(papers_path)

    with pytest.raises(ValueError, match="missing"):
        LanceRetriever(papers_path=str(papers_path), index_dir=index_dir, embedder=embedder)
