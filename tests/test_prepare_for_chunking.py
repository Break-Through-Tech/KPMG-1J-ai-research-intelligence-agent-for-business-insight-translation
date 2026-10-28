# unit tests for src/preprocessing/prepare_for_chunking.py, run from the project root with: python -m pytest tests/

import json
from datetime import date

import lancedb
import pandas as pd

from src.indexing.store import TABLE_NAME, make_schema
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


def make_index(index_dir, versions):
    """a tiny chunks table with one row per {paper_id: version}, no embedding model needed"""
    rows = [{"chunk_id": f"{paper_id}::0000", "paper_id": paper_id, "version": version, "chunk_index": 0,
             "vector": [0.5] * 4, "text": "t", "title": "t", "authors": ["a"], "arxiv_url": "u", "section": "s",
             "section_type": "method", "published_date": "2026-09-30", "primary_category": "cs.AI",
             "categories": ["cs.AI"]} for paper_id, version in versions.items()]
    lancedb.connect(index_dir).create_table(TABLE_NAME, data=rows, schema=make_schema(4))


def other_paper():
    return {**paper(), "arxiv_id": "2609.30265v1", "base_id": "2609.30265"}


def test_skip_indexed_leaves_out_papers_the_index_has(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper(), other_paper()])
    make_index(tmp_path / "index", {"2609.30264": 1})

    run_prepare(str(src), str(dst), skip_indexed=str(tmp_path / "index"))
    assert {r["paper_id"] for r in read_rows(dst)} == {"2609.30265"}


def test_skip_indexed_keeps_newer_versions(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper(version=2)])
    make_index(tmp_path / "index", {"2609.30264": 1})

    run_prepare(str(src), str(dst), skip_indexed=str(tmp_path / "index"))
    assert {r["version"] for r in read_rows(dst)} == {2}


def test_skip_indexed_with_no_index_yet_keeps_everything(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper(), other_paper()])

    run_prepare(str(src), str(dst), skip_indexed=str(tmp_path / "missing_index"))
    assert {r["paper_id"] for r in read_rows(dst)} == {"2609.30264", "2609.30265"}


def test_skip_indexed_can_leave_nothing_to_chunk(tmp_path):
    src, dst = tmp_path / "clean.parquet", tmp_path / "chunk_input.jsonl"
    write_papers(src, [paper()])
    make_index(tmp_path / "index", {"2609.30264": 1})

    assert run_prepare(str(src), str(dst), skip_indexed=str(tmp_path / "index")) == []
    assert read_rows(dst) == []
