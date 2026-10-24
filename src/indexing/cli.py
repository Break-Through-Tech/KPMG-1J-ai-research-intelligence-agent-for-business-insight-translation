# command line entry point for the indexing step
# ex: python -m src.indexing.cli                       # add new chunks from data/chunks.parquet
#     python -m src.indexing.cli --max-minutes 90         # stop after 90 minutes, the rest waits for the next run
#     python -m src.indexing.cli --rebuild             # start over, after changing the model or chunk settings
#     python -m src.indexing.cli --search "how are companies evaluating LLM agents?" --since 2026-09-01

import argparse
import json
from pathlib import Path

import pandas as pd

from ..vectorizing.embedder import DEFAULT_MODEL, TextEmbedder
from .store import open_index, open_paper_table, search, update_index, update_paper_vectors


def main():
    parser = argparse.ArgumentParser(description="build, update or search the chunk index")
    parser.add_argument("--chunks", default="data/chunks.parquet")
    parser.add_argument("--papers", default="data/papers_clean.parquet",
                        help="titles and abstracts for the paper vectors the retriever ranks papers by")
    parser.add_argument("--chunk-report", default="data/chunk_report.json", help="where the chunk settings are read from")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--rebuild", action="store_true",
                        help="delete the index and embed everything again. needs chunks for every paper, "
                             "so run prepare_for_chunking without --skip-indexed first")
    parser.add_argument("--search", help="run a query instead of updating")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--since", help="only papers published on or after this date (YYYY-MM-DD)")
    parser.add_argument("--max-minutes", type=float,
                        help="stop adding papers after this long; what's done is saved and the rest waits for the next run")
    args = parser.parse_args()

    # fail before touching the index, so a missing input never leaves a half-made index behind
    if not args.search and not Path(args.chunks).exists():
        raise SystemExit(f"{args.chunks} not found, run the chunking step first: python -m src.chunking.cli")

    embedder = TextEmbedder(model_name=args.model)
    report = Path(args.chunk_report)
    chunk_config = json.loads(report.read_text())["config"] if report.exists() else None
    table = open_index(args.index_dir, embedder, chunk_config, rebuild=args.rebuild)
    if args.rebuild:
        open_paper_table(args.index_dir, embedder.model.get_embedding_dimension(), rebuild=True)

    if args.search:
        where = f"published_date >= '{args.since}'" if args.since else None
        for i, r in enumerate(search(table, embedder, args.search, k=args.k, where=where), 1):
            print(f"{i}. {r['title']} ({r['published_date']}) [{r['section']}]\n   {r['arxiv_url']}\n   {r['text'][:200]}...\n")
        return

    max_seconds = args.max_minutes * 60 if args.max_minutes else None
    added = update_index(table, pd.read_parquet(args.chunks), embedder, args.index_dir, max_seconds=max_seconds)
    print(f"added {added:,} chunks, index now has {table.count_rows():,}")

    # short texts, so this takes about a minute even when an older index has none yet
    if Path(args.papers).exists():
        papers = pd.read_parquet(args.papers, columns=["base_id", "version", "title", "abstract_clean"])
        n = update_paper_vectors(args.index_dir, table, papers, embedder)
        print(f"embedded {n:,} paper titles and abstracts")
    else:
        print(f"{args.papers} not found, skipping paper vectors (the retriever embeds them at startup instead)")


if __name__ == "__main__":
    main()
