# command line entry point for the indexing step
# ex: python -m src.indexing.cli                       # add new chunks from data/chunks.parquet
#     python -m src.indexing.cli --rebuild             # start over, after changing the model or chunk settings
#     python -m src.indexing.cli --search "how are companies evaluating LLM agents?" --since 2026-09-01

import argparse
import json
from pathlib import Path

import pandas as pd

from ..vectorizing.embedder import DEFAULT_MODEL, TextEmbedder
from .store import open_index, search, update_index


def main():
    parser = argparse.ArgumentParser(description="build, update or search the chunk index")
    parser.add_argument("--chunks", default="data/chunks.parquet")
    parser.add_argument("--chunk-report", default="data/chunk_report.json", help="where the chunk settings are read from")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--rebuild", action="store_true", help="delete the index and embed everything again")
    parser.add_argument("--search", help="run a query instead of updating")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--since", help="only papers published on or after this date (YYYY-MM-DD)")
    args = parser.parse_args()

    embedder = TextEmbedder(model_name=args.model)
    report = Path(args.chunk_report)
    chunk_config = json.loads(report.read_text())["config"] if report.exists() else None
    table = open_index(args.index_dir, embedder, chunk_config, rebuild=args.rebuild)

    if args.search:
        where = f"published_date >= '{args.since}'" if args.since else None
        for i, r in enumerate(search(table, embedder, args.search, k=args.k, where=where), 1):
            print(f"{i}. {r['title']} ({r['published_date']}) [{r['section']}]\n   {r['arxiv_url']}\n   {r['text'][:200]}...\n")
        return

    added = update_index(table, pd.read_parquet(args.chunks), embedder, args.index_dir)
    print(f"added {added:,} chunks, index now has {table.count_rows():,}")


if __name__ == "__main__":
    main()
