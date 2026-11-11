from src.pipeline.compress import (
    GAP,
    CompressSettings,
    ContextCompressor,
    approx_tokens,
    clean_text,
    join_kept,
    select_sentences,
    split_sentences,
    strip_overlap,
)
from src.pipeline.pipeline import EXCERPT_NOTE, answer_query, format_retrieved_content

from tests.test_pipeline import FakeLLM, FakeRetriever


def test_clean_text_removes_citations_but_keeps_numbers():
    text = ("Accuracy rose to 82.4% [12] on GSM8K (Smith et al., 2025; Lee, 2024), "
            "see https://github.com/x/y. Wang et al. (2026) report **31.6%** with \\cite{foo} 3.5_±1.4.")
    cleaned = clean_text(text)

    assert "[12]" not in cleaned and "Smith" not in cleaned and "github" not in cleaned
    assert "\\cite" not in cleaned and "**" not in cleaned
    assert "82.4%" in cleaned and "GSM8K" in cleaned and "31.6%" in cleaned
    assert "Wang et al. report" in cleaned
    assert "3.5±1.4" in cleaned


def test_clean_text_leaves_arxiv_style_ids_alone():
    assert "[2609.38107]" in clean_text("as shown in [2609.38107].")


def test_split_sentences_keeps_abbreviations_together():
    sentences = split_sentences("Smith et al. found gains. See Fig. 2 for details. It works, e.g. on GSM8K.")
    assert sentences == ["Smith et al. found gains.", "See Fig. 2 for details.", "It works, e.g. on GSM8K."]


def test_strip_overlap_removes_the_repeated_opening():
    earlier = "First part of the section. The shared sentence that both chunks carry."
    later = "The shared sentence that both chunks carry. New text continues here."
    assert strip_overlap(earlier, later) == "New text continues here."
    assert strip_overlap("unrelated", later) == later


def test_select_sentences_keeps_neighbors_numbers_and_caveats():
    sentences = [f"Plain sentence {c}." for c in "abcdefghij"]
    sentences[8] = "However, it fails on long inputs."
    scores = [0] * 10
    scores[2] = 1.0
    scores[5] = 0.9
    kept = select_sentences(sentences, scores, CompressSettings(neighbors=2, must_keep_neighbors=1, top_share=0.2))
    # 2 and 5 with two either side, the caveat at 8 with one either side
    assert kept == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

    kept = select_sentences(sentences, scores, CompressSettings(neighbors=0, must_keep_neighbors=0, top_share=0.2))
    assert kept == [2, 5, 8]


def test_join_kept_marks_gaps():
    text = join_kept(["A.", "B.", "C.", "D."], [1, 3])
    assert text == "[...] B." + GAP + "D."


def paper(rank, best_text, passages=()):
    return {
        "paper_id": f"2609.0000{rank}v1",
        "title": f"Paper {rank}",
        "abstract": f"Abstract of paper {rank}.",
        "chunk_id": f"2609.0000{rank}::0004",
        "best_chunk_section": "4 Results",
        "best_chunk_section_type": "results",
        "best_chunk_text": best_text,
        "passages": list(passages),
    }


def passage(label, chunk, text, section="6 Limitations", section_type="limitations"):
    return {"label": label, "section": section, "section_type": section_type,
            "chunk_id": chunk, "text": text}


WORDS = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike".split()


def filler(topic, n=40):
    """n sentences with no numbers or caveat words, all different."""
    return " ".join(f"The {topic} {WORDS[i % 13]} {WORDS[(i // 13) % 13]} step is described plainly." for i in range(n))


def test_compress_drops_lowest_tier_first_when_over_budget():
    papers = [
        paper(1, filler("setup"), [
            passage("results", "2609.00001::0009", filler("result"), "5 Experiments", "experiments"),
            passage("limitations", "2609.00001::0012", "The method only works on English text."),
        ]),
        paper(2, filler("design", 10), [passage("limitations", "2609.00002::0010", "It cannot handle images.")]),
    ]
    compressor = ContextCompressor(settings=CompressSettings(budget_tokens=900, top_share=1.0,
                                                             neighbors=0, must_keep_neighbors=0))
    short, stats = compressor.compress("how is the setup described", papers)

    # the results passage of a paper whose best chunk is already results goes first
    assert {"paper_id": "2609.00001v1", "kind": "results", "chunk_id": "2609.00001::0009"} in stats["dropped"]
    assert all(d["kind"] != "limitations" for d in stats["dropped"])
    assert [p["label"] for p in short[0]["passages"]] == ["limitations"]
    assert stats["tokens_after"] <= 900
    # the input papers aren't changed
    assert len(papers[0]["passages"]) == 2


def test_compress_removes_overlap_and_repeated_abstract_sentences():
    shared = "The shared overlap sentence appears at the end of one chunk and the start of the next."
    papers = [paper(1, "Main finding is 42%. " + shared, [
        passage("results", "2609.00001::0005", shared + " Accuracy reached 91%.", "4 Results", "results"),
        passage("limitations", "2609.00001::0012", "Abstract of paper 1. It needs labels."),
    ])]
    short, _ = ContextCompressor().compress("finding", papers)

    assert short[0]["passages"][0]["text"] == "Accuracy reached 91%."
    assert short[0]["passages"][1]["text"] == "It needs labels."


def test_pipeline_uses_compressor_and_saves_its_stats():
    long_text = filler("method", 60) + " Accuracy was 77.7%."
    papers = [paper(1, long_text)]
    llm = FakeLLM(response="Key Findings: 77.7%. [2609.00001v1]")

    result = answer_query("accuracy", FakeRetriever(papers), llm, translate=False,
                          compressor=ContextCompressor())

    prompt = llm.calls[0][1]
    assert EXCERPT_NOTE in prompt
    assert "77.7%" in prompt
    assert result["context"]["tokens_after"] < result["context"]["tokens_before"]


def test_format_skips_main_chunk_when_budget_dropped_it():
    content = format_retrieved_content([{**paper(1, ""), "passages": []}])
    assert "Chunk ID" not in content
    assert "Abstract of paper 1." in content


def test_approx_tokens():
    assert approx_tokens("abcd" * 10) == 10
