# unit tests for src/preprocessing/prepare_for_chunking.py, run from the project root with: python -m pytest tests/

import json
from datetime import date

import pandas as pd

from src.preprocessing.prepare_for_chunking import prepare_paper, run_prepare


def paper(version=1, text="Body text of the method section.", usable=True):
    return {
        "arxiv_id": f"2609.30264v{version}", "base_id": "2609.30264", "version": version,
        "title": "Agents for Insight", "authors": ["Jane Doe"], "abs_url": f"http://arxiv.org/abs/2609.30264v{version}",
        "published_date": date(2026, 9, 30), "primary_category": "cs.AI", "categories": ["cs.AI", "cs.CL"],
        "abstract_clean": "An abstract.", "body_text": text, "is_usable": usable, "quality_issues": [],
        "sections": [{"number": "1", "heading": "Method", "section_type": "method", "text": text}],
    }


def write_papers(path, papers):
    pd.DataFrame(papers).to_parquet(path, index=False)


def read_rows(path):
    return [json.loads(l) for l in open(path)]


def test_ids_have_no_version_and_filter_fields_are_kept():
    rows = prepare_paper(paper(version=2))
    assert all(r["paper_id"] == "2609.30264" and r["version"] == 2 for r in rows)
    assert rows[0]["section_id"] == "2609.30264_sec00"
    assert rows[0]["published_date"] == "2026-09-30"
    assert rows[0]["primary_category"] == "cs.AI" and rows[0]["categories"] == ["cs.AI", "cs.CL"]
    json.dumps(rows)  # everything must be writable to jsonl


def test_append_twice_adds_nothing(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper()])
    run_prepare(str(src), str(dst))
    before = read_rows(dst)
    assert run_prepare(str(src), str(dst), append=True) == []
    assert read_rows(dst) == before


def test_append_replaces_older_version(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper(version=1, text="Old method text.")])
    run_prepare(str(src), str(dst))
    write_papers(src, [paper(version=2, text="New method text.")])
    run_prepare(str(src), str(dst), append=True)
    rows = read_rows(dst)
    assert {r["version"] for r in rows} == {2}
    assert not any("Old method" in r["text"] for r in rows)


def test_unusable_papers_are_skipped(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper(usable=False)])
    assert run_prepare(str(src), str(dst)) == []
