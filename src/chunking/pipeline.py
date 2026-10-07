# chunking pipeline: chunk_input.jsonl (from prepare_for_chunking.py) -> data/chunks.parquet

import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .chunker import ChunkConfig, chunk_paper


def load_section_rows(path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def run_chunking(input_path="data/chunk_input.jsonl", output_path="data/chunks.parquet",
                 report_path="data/chunk_report.json", cfg: ChunkConfig = ChunkConfig()) -> pd.DataFrame:
    if not Path(input_path).exists():
        raise FileNotFoundError(f"{input_path} not found, run prepare_for_chunking.py first")

    rows = load_section_rows(input_path)
    by_paper = {}  # keeps reading order: rows arrive in order within each paper
    for r in rows:
        by_paper.setdefault(r["paper_id"], []).append(r)
    print(f"chunking {len(rows):,} sections from {len(by_paper):,} papers")

    chunks = pd.DataFrame([c for paper_rows in by_paper.values() for c in chunk_paper(paper_rows, cfg)])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    chunks.to_parquet(output_path, index=False)

    per_paper = chunks.groupby("paper_id").size()
    report = {
        "config": asdict(cfg),
        "sections_in": len(rows),
        "papers_chunked": int(chunks["paper_id"].nunique()),
        "chunks": len(chunks),
        "chunks_per_paper": {"median": float(per_paper.median()), "min": int(per_paper.min()), "max": int(per_paper.max())},
        "tokens_per_chunk": {"median": float(chunks["n_tokens"].median()), "max": int(chunks["n_tokens"].max())},
        "chunks_under_50_tokens": int((chunks["n_tokens"] < 50).sum()),
        "total_tokens": int(chunks["n_tokens"].sum()),
        "chunks_by_section_type": chunks["section_type"].value_counts().to_dict(),
        "duplicate_chunk_ids": int(chunks["chunk_id"].duplicated().sum()),
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"wrote {len(chunks):,} chunks to {output_path} "
          f"(median {report['chunks_per_paper']['median']:.0f} per paper, "
          f"median {report['tokens_per_chunk']['median']:.0f} tokens per chunk)")
    print(f"wrote {report_path}")
    return chunks
