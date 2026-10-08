# tests for batch saving / oldest-first ingestion and the coverage check
# arXiv is never called: fetch, download and extract are replaced with fakes
# run from the project root with: python -m pytest tests/

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from src.ingestion import pipeline
from src.ingestion.check_coverage import check_coverage

START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _fake_papers(n):
    # newest first, the way the arXiv API returns them
    papers = []
    for i in reversed(range(n)):
        papers.append({
            "arxiv_id": f"2610.{i:05d}v1", "title": f"paper {i}", "abstract": "abs", "authors": ["A"],
            "primary_category": "cs.AI", "categories": ["cs.AI"],
            "published": START + timedelta(hours=i), "updated": START + timedelta(hours=i),
            "pdf_url": "", "abs_url": "",
        })
    return papers


@pytest.fixture
def fake_arxiv(monkeypatch):
    """replaces the network steps; returns a dict to inspect what was processed"""
    state = {"available": _fake_papers(10), "processed": [], "fail_on_call": None, "calls": 0}

    monkeypatch.setattr(pipeline, "fetch_metadata", lambda category, max_results, since: [dict(p) for p in state["available"]])

    def fake_download(papers, raw_pdf_dir):
        state["calls"] += 1
        if state["fail_on_call"] == state["calls"]:
            raise RuntimeError("simulated crash")
        for p in papers:
            p["pdf_path"] = f"{raw_pdf_dir}/{p['arxiv_id']}.pdf"
            p["download_status"] = "downloaded"
        return papers

    def fake_extract(papers):
        for p in papers:
            p["extracted_text"] = "text"
            p["extraction_status"] = "extracted"
            state["processed"].append(p["arxiv_id"])
        return papers

    monkeypatch.setattr(pipeline, "download_all", fake_download)
    monkeypatch.setattr(pipeline, "extract_all", fake_extract)
    return state


def test_oldest_first_and_saved_per_batch(fake_arxiv, tmp_path):
    path = tmp_path / "papers.parquet"
    df = pipeline.run_pipeline(dataset_path=str(path), raw_pdf_dir=str(tmp_path), batch_size=4)
    assert fake_arxiv["calls"] == 3                                       # 10 papers in batches of 4
    assert fake_arxiv["processed"] == [f"2610.{i:05d}v1" for i in range(10)]  # oldest first
    assert len(df) == 10 and len(pd.read_parquet(path)) == 10


def test_crash_keeps_finished_batches(fake_arxiv, tmp_path):
    path = tmp_path / "papers.parquet"
    fake_arxiv["fail_on_call"] = 2
    with pytest.raises(RuntimeError):
        pipeline.run_pipeline(dataset_path=str(path), raw_pdf_dir=str(tmp_path), batch_size=4)
    saved = pd.read_parquet(path)
    assert sorted(saved["arxiv_id"]) == [f"2610.{i:05d}v1" for i in range(4)]  # batch 1 survived


def test_max_papers_leaves_backlog_for_next_run_without_gaps(fake_arxiv, tmp_path):
    path = str(tmp_path / "papers.parquet")
    pipeline.run_pipeline(dataset_path=path, raw_pdf_dir=str(tmp_path), max_papers=6, batch_size=3)
    assert sorted(pd.read_parquet(path)["arxiv_id"]) == [f"2610.{i:05d}v1" for i in range(6)]

    # next run picks up exactly the 4 that were left, no duplicates
    pipeline.run_pipeline(dataset_path=path, raw_pdf_dir=str(tmp_path), max_papers=6, batch_size=3)
    saved = pd.read_parquet(path)
    assert len(saved) == 10 and saved["arxiv_id"].is_unique


def test_default_behavior_unchanged(fake_arxiv, tmp_path):
    path = tmp_path / "papers.parquet"
    pipeline.run_pipeline(dataset_path=str(path), raw_pdf_dir=str(tmp_path))
    assert fake_arxiv["calls"] == 1 and len(pd.read_parquet(path)) == 10


def test_nothing_new(fake_arxiv, tmp_path):
    path = str(tmp_path / "papers.parquet")
    pipeline.run_pipeline(dataset_path=path, raw_pdf_dir=str(tmp_path), batch_size=5)
    calls = fake_arxiv["calls"]
    pipeline.run_pipeline(dataset_path=path, raw_pdf_dir=str(tmp_path), batch_size=5)
    assert fake_arxiv["calls"] == calls


# ---------- coverage check ----------

def _dataset(tmp_path, ids_status):
    rows = [{"arxiv_id": f"{i}v1", "published": START + timedelta(hours=h), "ingestion_status": s}
            for h, (i, s) in enumerate(ids_status)]
    path = tmp_path / "papers.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)
    return str(path)


def test_coverage_finds_missing_and_failed(tmp_path):
    path = _dataset(tmp_path, [("a", "complete"), ("b", "failed"), ("c", "complete"), ("d", "complete")])
    result = check_coverage(path, "cat:cs.AI", date(2026, 10, 1), fetch_ids=lambda c, s, e: {"a", "b", "c", "x"})
    assert result["missing"] == ["x"]
    assert result["incomplete"] == ["b"]


def test_coverage_all_present(tmp_path):
    path = _dataset(tmp_path, [("a", "complete"), ("b", "complete"), ("c", "complete")])
    result = check_coverage(path, "cat:cs.AI", date(2026, 10, 1), fetch_ids=lambda c, s, e: {"a", "b"})
    assert result["missing"] == [] and result["expected"] == 2


def test_coverage_window_ends_before_newest_saved_paper(tmp_path):
    path = _dataset(tmp_path, [("a", "complete"), ("b", "complete")])
    seen = {}
    def fake_fetch(category, start, end):
        seen["end"] = end
        return set()
    check_coverage(path, "cat:cs.AI", date(2026, 10, 1), fetch_ids=fake_fetch)
    assert seen["end"] < START + timedelta(hours=1)  # newest saved paper is at +1h


# ---------- bad characters and outages ----------

def test_lone_surrogate_in_extracted_text_does_not_crash_the_save(fake_arxiv, tmp_path, monkeypatch):
    # pymupdf4llm returned "\ud835" (half of a math-font character) for a real paper, which crashed the batch save
    def extract_with_bad_char(papers):
        for p in papers:
            p["extracted_text"] = "uses the \ud835 math font"
            p["extraction_status"] = "extracted"
        return papers
    monkeypatch.setattr(pipeline, "extract_all", extract_with_bad_char)

    path = tmp_path / "papers.parquet"
    pipeline.run_pipeline(dataset_path=str(path), raw_pdf_dir=str(tmp_path), batch_size=5)
    saved = pd.read_parquet(path)
    assert len(saved) == 10
    assert not any("\ud835" in text for text in saved["extracted_text"])


def test_merge_and_save_strips_surrogates_from_any_field(tmp_path):
    from src.ingestion.dataset import merge_and_save
    row = {"arxiv_id": "x1v1", "title": "bad \udc00 title", "extracted_text": "ok",
           "download_status": "downloaded", "extraction_status": "extracted"}
    merge_and_save(pd.DataFrame(), [row], str(tmp_path / "p.parquet"))
    assert pd.read_parquet(tmp_path / "p.parquet")["title"][0] == "bad  title"


def _run_coverage_cli(monkeypatch, path, fetch):
    import sys
    from src.ingestion import check_coverage as cc
    monkeypatch.setattr(cc, "arxiv_ids_in_window", fetch)
    monkeypatch.setattr(sys, "argv", ["check_coverage", "--dataset", path, "--since", "2026-10-01", "--strict"])
    cc.main()


def test_coverage_cli_warns_but_passes_when_arxiv_is_down(tmp_path, monkeypatch, capsys):
    from src.ingestion.check_coverage import ArxivUnavailable
    path = _dataset(tmp_path, [("a", "complete"), ("b", "complete")])
    def down(category, start, end):
        raise ArxivUnavailable("503")
    _run_coverage_cli(monkeypatch, path, down)   # no SystemExit = the run stays green
    assert "::warning::" in capsys.readouterr().out


def test_coverage_cli_fails_when_papers_are_missing(tmp_path, monkeypatch):
    path = _dataset(tmp_path, [("a", "complete"), ("b", "complete")])
    with pytest.raises(SystemExit) as exit_info:
        _run_coverage_cli(monkeypatch, path, lambda c, s, e: {"a", "zzz"})
    assert exit_info.value.code == 1


class _FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body


def test_html_error_page_is_not_saved_as_pdf(tmp_path, monkeypatch):
    from src.ingestion import download_pdfs
    monkeypatch.setattr(download_pdfs.requests, "get", lambda *a, **k: _FakeResponse(b"<html>rate limited</html>"))
    dest = tmp_path / "pdfs" / "2609.00001v1.pdf"
    assert download_pdfs.download_pdf("2609.00001v1", "http://x", str(dest)) == "failed"
    assert not dest.exists() and not (tmp_path / "pdfs" / "2609.00001v1.pdf.part").exists()


def test_real_pdf_is_saved(tmp_path, monkeypatch):
    from src.ingestion import download_pdfs
    monkeypatch.setattr(download_pdfs.requests, "get", lambda *a, **k: _FakeResponse(b"%PDF-1.5 fake body"))
    dest = tmp_path / "pdfs" / "2609.00001v1.pdf"
    assert download_pdfs.download_pdf("2609.00001v1", "http://x", str(dest)) == "downloaded"
    assert dest.read_bytes().startswith(b"%PDF-")


def test_failed_extraction_deletes_pdf_so_it_is_redownloaded(tmp_path, monkeypatch):
    from src.ingestion import extract_text
    pdf = tmp_path / "2609.00001v1.pdf"
    pdf.write_bytes(b"%PDF-1.5 corrupt")
    monkeypatch.setattr(extract_text, "extract_text", lambda path: None)
    papers = extract_text.extract_all([{"download_status": "downloaded", "pdf_path": str(pdf)}])
    assert papers[0]["extraction_status"] == "failed" and not pdf.exists()
