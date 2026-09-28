# argparse entrypoint
# command line entrypoint for the pipeline, so it passes arguments like category, max results etc
# then passes them to run_pipeline in pipeline
# ex: python -m src.ingestion.cli --max-results 10 --since 2026-01-01

import argparse
from datetime import date
from .pipeline import run_pipeline

def main():
    parser = argparse.ArgumentParser(description = "ingest arXiv papers")
    parser.add_argument("--category", default="cat:cs.AI")
    parser.add_argument("--max-results", type=int, default=50)
    parser.add_argument("--since", type=date.fromisoformat, default=None)
    parser.add_argument("--raw-pdf-dir", default="data/raw_pdfs")
    parser.add_argument("--dataset-path", default="data/papers.parquet")
    args = parser.parse_args()

    run_pipeline(
        category=args.category,
        max_results=args.max_results,
        raw_pdf_dir=args.raw_pdf_dir,
        dataset_path=args.dataset_path,
        since=args.since,
    )

if __name__ == "__main__":
    main()