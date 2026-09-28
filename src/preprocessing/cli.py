# command line entrypoint for the preprocessing step
# ex: python -m src.preprocessing.cli --input data/papers.parquet --output data/papers_clean.parquet

import argparse
from .pipeline import run_preprocessing

def main():
    parser = argparse.ArgumentParser(description="clean and structure ingested arXiv papers")
    parser.add_argument("--input", default="data/papers.parquet")
    parser.add_argument("--output", default="data/papers_clean.parquet")
    parser.add_argument("--report", default="data/preprocess_report.json")
    args = parser.parse_args()

    run_preprocessing(input_path=args.input, output_path=args.output, report_path=args.report)

if __name__ == "__main__":
    main()
