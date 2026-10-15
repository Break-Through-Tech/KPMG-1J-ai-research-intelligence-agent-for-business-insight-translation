# unit tests for src/rag/lance_retriever.py
# builds a tiny LanceDB index with the real embedding model, like tests/test_indexing.py

import pandas as pd
import pytest

from src.indexing.store import open_index, update_index
from src.pipeline.pipeline import answer_query
from src.rag.lance_retriever import LanceCombinedRetriever, LanceRetriever, rrf_merge
from src.vectorizing.embedder import TextEmbedder

PAPERS = {
    "2609.00001": ("Retrieval Augmented Generation for Audits",
                   "We retrieve passages from financial filings before generating an answer.",
                   ["Auditors need answers grounded in financial filings.",
                    "Retrieval augmented generation reduced unsupported claims in audit reports."]),
    "2609.00002": ("Robot Grasping with Tactile Sensors",
                   "A gripper uses touch sensors to pick up fragile objects.",
                   ["Tactile sensors measure contact force on each finger.",
                    "The gripper picked up eggs without breaking them."]),
    "2609.00003": ("Parameter Efficient Fine Tuning",
                   "We study the zorblax adapter, a low rank method for tuning large models.",
                   ["Low rank adapters update a small number of weights.",
                    "The zorblax adapter matched full fine tuning on reading tasks."]),
}

# what the pipeline reads from each result
PIPELINE_KEYS = {"paper_id", "title", "abstract", "score", "chunk_id",
                 "best_chunk_section", "best_chunk_text"}


def make_chunks():
    rows = []
    for paper_id, (title, _, texts) in PAPERS.items():
        for i, text in enumerate(texts):
            section = "1 Introduction" if i == 0 else "4 Results"
            rows.append({
                "chunk_id": f"{paper_id}::{i:04d}", "paper_id": paper_id, "version": 1, "chunk_index": i,
                "title": title, "authors": ["Jane Doe"], "arxiv_url": f"http://arxiv.org/abs/{paper_id}v1",
                "section": section, "section_type": "results" if i else "introduction",
                "published_date": "2026-09-01", "primary_category": "cs.AI", "categories": ["cs.AI"],
                "text": text, "text_for_embedding": f"{title}\nSection: {section}\n\n{text}",
            })
    return pd.DataFrame(rows)


class FakeLLM:

    def generate(self, system_prompt, user_prompt):
        return "Key Findings: grounded answers. [2609.00001v1]"


@pytest.fixture(scope="module")
def embedder():
    return TextEmbedder()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory, embedder):
    folder = tmp_path_factory.mktemp("lance")
    index_dir = folder / "index"
    table = open_index(index_dir, embedder)
    update_index(table, make_chunks(), embedder, index_dir)

    papers_path = folder / "papers_clean.parquet"
    pd.DataFrame([
        {"arxiv_id": f"{paper_id}v1", "title": title, "abstract_clean": abstract}
        for paper_id, (title, abstract, _) in PAPERS.items()
    ]).to_parquet(papers_path)

    return str(papers_path), str(index_dir)


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
    assert result["best_chunk_text"] in PAPERS["2609.00001"][2]


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
