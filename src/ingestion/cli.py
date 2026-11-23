# argparse entrypoint
# command line entrypoint for the pipeline, so it passes arguments like category, max results etc
# then passes them to run_pipeline in pipeline
# ex: python -m src.ingestion.cli --max-results 10 --since 2026-01-01

import argparse
import sys
from datetime import date

from . import arxiv_api
from .pipeline import run_pipeline

# exit code when arXiv refused every request from the start, which means it's blocking this
# machine; retrying from the same machine doesn't help (scripts/pull_recent_papers.sh stops,
# and the workflow's catch-up run tries again later, usually from a different machine)
BLOCKED_EXIT_CODE = 75

def main():
    parser = argparse.ArgumentParser(description = "ingest arXiv papers")
    parser.add_argument("--category", default="cat:cs.AI")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    parser.add_argument("--raw-pdf-dir", default="data/raw_pdfs")
    parser.add_argument("--dataset-path", default="data/papers.parquet")
    parser.add_argument("--max-papers", type=int, default=None, help="cap on new papers processed this run (the rest wait for the next run)")
    parser.add_argument("--batch-size", type=int, default=None, help="save progress every N papers")
    args = parser.parse_args()

    try:
        run_pipeline(
            category=args.category,
            max_results=args.max_results,
            raw_pdf_dir=args.raw_pdf_dir,
            dataset_path=args.dataset_path,
            since=args.since,
            max_papers=args.max_papers,
            batch_size=args.batch_size,
        )
    except arxiv_api.ArxivUnavailable as error:
        if arxiv_api.ever_succeeded():
            raise  # failed partway, usually brief, so the script retries
        print(f"arXiv refused every request from this machine ({error}). "
              "It's likely blocking this machine's IP address.", file=sys.stderr)
        sys.exit(BLOCKED_EXIT_CODE)

if __name__ == "__main__":
    main()