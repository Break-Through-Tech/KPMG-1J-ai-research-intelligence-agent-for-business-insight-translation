# unit tests for src/chunking, run from the project root with: python -m pytest tests/
# input rows follow the format of chunk_input.jsonl from prepare_for_chunking.py

from src.chunking.chunker import ChunkConfig, chunk_paper, count_tokens, merge_short_sections, split_sentences, window_text

PROSE = ("Large language models are increasingly used for business analysis. "
         "We measure how often they agree with expert analysts on 1,200 filings. "
         "Agreement was 81.4% overall, with lower scores on forward-looking statements. ")

META = {"paper_id": "2609.30264v1", "title": "Agents for Insight", "authors": ["Jane Doe", "John Smith"],
        "arxiv_url": "http://arxiv.org/abs/2609.30264v1"}


def row(i, section, section_type, text, source="body"):
    return {**META, "section_id": f"2609.30264v1_sec{i:02d}", "section": section,
            "section_type": section_type, "source": source, "text": text, "est_tokens": len(text) // 4}


ROWS = [
    row(0, "Abstract (arXiv metadata)", "abstract", PROSE.strip(), source="abstract_clean"),
    row(1, "1 Introduction", "introduction", PROSE * 6),
    row(2, "2.1 Setup", "method", PROSE * 12),
    row(3, "2.2 Note", "method", "Short note."),
    row(4, "3 Results", "results", "| model | accuracy |\n|---|---|\n| A | 0.81 |\n\n" + PROSE * 4),
]

SMALL = ChunkConfig(chunk_tokens=80, overlap_tokens=20)


# ---------- sentences ----------

def test_sentences_respect_abbreviations_and_decimals():
    s = split_sentences("We follow Doe et al. in Fig. 3 and report 81.4% accuracy. The rest is e.g. noise. Done.")
    assert s == ["We follow Doe et al. in Fig. 3 and report 81.4% accuracy.", "The rest is e.g. noise.", "Done."]


def test_table_rows_stay_separate():
    assert split_sentences("| a | b |\n|---|---|\n| 1 | 2 |") == ["| a | b |", "|---|---|", "| 1 | 2 |"]


# ---------- windows ----------

def test_chunks_never_exceed_size():
    assert all(count_tokens(c) <= SMALL.chunk_tokens for c in window_text(PROSE * 30, SMALL))


def test_sentences_are_not_cut():
    sentences = set(split_sentences(PROSE * 30))
    for chunk in window_text(PROSE * 30, SMALL):
        assert all(s in sentences for s in split_sentences(chunk))


def test_neighbouring_chunks_overlap():
    chunks = window_text(PROSE * 30, SMALL)
    assert len(chunks) > 2
    for a, b in zip(chunks, chunks[1:]):
        assert b.startswith(split_sentences(a)[-1])


def test_oversized_sentence_is_hard_split():
    chunks = window_text("word " * 1000, SMALL)
    assert len(chunks) > 1 and all(count_tokens(c) <= SMALL.chunk_tokens for c in chunks)


# ---------- papers ----------

def test_metadata_on_every_chunk():
    chunks = chunk_paper(ROWS, SMALL)
    for c in chunks:
        assert all(c[k] for k in ["paper_id", "title", "authors", "section", "arxiv_url", "chunk_id"])
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)
    assert chunks[1]["chunk_id"] == "2609.30264v1::0001"


def test_abstract_comes_first():
    assert chunk_paper(ROWS, SMALL)[0]["section_type"] == "abstract"


def test_chunk_never_spans_two_sections():
    for c in chunk_paper(ROWS, SMALL):
        if c["section"] == "1 Introduction":
            assert "accuracy" not in c["text"]   # results table stays in section 3


def test_short_section_is_merged_into_next():
    merged = merge_short_sections(ROWS, SMALL)
    assert "2.2 Note" not in [r["section"] for r in merged]
    results = next(r for r in merged if r["section"] == "3 Results")
    assert results["text"].startswith("Short note.") and results["merged_from"] == ["2.2 Note"]


def test_short_last_section_joins_previous():
    merged = merge_short_sections(ROWS[:3] + [row(9, "5 End", "conclusion", "Thanks.")], SMALL)
    assert merged[-1]["section"] == "2.1 Setup" and merged[-1]["text"].endswith("Thanks.")


def test_embedding_text_has_title_and_section():
    c = chunk_paper(ROWS, SMALL)[2]
    assert c["text_for_embedding"].startswith(f"Agents for Insight\nSection: {c['section']}\n\n")


def test_no_headings_row_gets_a_label():
    chunks = chunk_paper([row(0, "", "body", PROSE * 10, source="body_text")], SMALL)
    assert chunks and all(c["section"] == "(no section)" for c in chunks)


def test_empty_rows_are_skipped():
    assert chunk_paper([row(0, "1 Intro", "introduction", "   ")], SMALL) == []
