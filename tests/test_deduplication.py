import pandas as pd
from src.vectorizing.embedder import TextEmbedder
from src.indexing.store import open_index, update_index, search


def _make_chunks(paper_chunks: dict[str, int]) -> pd.DataFrame:
    """
    Build a minimal chunks DataFrame.
    paper_chunks: {"paper_id": number_of_chunks, ...}
    """
    rows = []
    for paper_id, n in paper_chunks.items():
        for i in range(n):
            rows.append({
                "chunk_id": f"{paper_id}-{i}",
                "paper_id": paper_id,
                "version": 1,
                "chunk_index": i,
                "text": "retrieval augmented generation for audits",
                "text_for_embedding": "retrieval augmented generation for audits",
                "title": f"Paper {paper_id}",
                "authors": ["A"],
                "arxiv_url": "",
                "section": "intro",
                "section_type": "intro",
                "published_date": "2026-01-01",
                "primary_category": "cs.AI",
                "categories": ["cs.AI"],
            })
    return pd.DataFrame(rows)


def _build_index(tmp_path, paper_chunks: dict[str, int]):
    embedder = TextEmbedder()
    table = open_index(str(tmp_path), embedder, rebuild=True)
    chunks = _make_chunks(paper_chunks)
    update_index(table, chunks, embedder, str(tmp_path))
    return table, embedder


def test_deduplication_limits_chunks_per_paper(tmp_path):
    # 5 chunks from paper1, 1 from paper2 — max_per_paper=1 should cap paper1 at 1
    table, embedder = _build_index(tmp_path, {"paper1": 5, "paper2": 1})

    results = search(table, embedder, "retrieval augmented generation", k=6, max_per_paper=1)
    paper_ids = [r["paper_id"] for r in results]

    assert paper_ids.count("paper1") <= 1
    assert paper_ids.count("paper2") <= 1


def test_max_per_paper_two_allows_two_chunks(tmp_path):
    # 5 chunks from paper1 — max_per_paper=2 should allow up to 2 from paper1
    table, embedder = _build_index(tmp_path, {"paper1": 5, "paper2": 1})

    results = search(table, embedder, "retrieval augmented generation", k=6, max_per_paper=2)
    paper_ids = [r["paper_id"] for r in results]

    assert paper_ids.count("paper1") <= 2
    assert paper_ids.count("paper2") <= 2


def test_returns_exactly_k_results(tmp_path):
    # 10 papers with 3 chunks each — asking for k=5 should return exactly 5
    table, embedder = _build_index(tmp_path, {f"paper{i}": 3 for i in range(10)})

    results = search(table, embedder, "retrieval augmented generation", k=5, max_per_paper=1)

    assert len(results) == 5


def test_single_paper_returns_up_to_max_per_paper(tmp_path):
    # all chunks come from the same paper — result count is capped at max_per_paper
    table, embedder = _build_index(tmp_path, {"paper1": 5})

    results = search(table, embedder, "retrieval augmented generation", k=5, max_per_paper=1)

    assert len(results) == 1
    assert results[0]["paper_id"] == "paper1"


def test_k_larger_than_unique_papers_does_not_crash(tmp_path):
    # only 3 unique papers but k=10 — should return 3 results without crashing
    table, embedder = _build_index(tmp_path, {"paper1": 2, "paper2": 2, "paper3": 2})

    results = search(table, embedder, "retrieval augmented generation", k=10, max_per_paper=1)

    assert len(results) == 3
    assert len(set(r["paper_id"] for r in results)) == 3


def test_default_max_per_paper_is_one(tmp_path):
    # calling search() without max_per_paper should default to 1 chunk per paper
    table, embedder = _build_index(tmp_path, {"paper1": 5, "paper2": 5})

    results = search(table, embedder, "retrieval augmented generation", k=4)
    paper_ids = [r["paper_id"] for r in results]

    assert paper_ids.count("paper1") <= 1
    assert paper_ids.count("paper2") <= 1
