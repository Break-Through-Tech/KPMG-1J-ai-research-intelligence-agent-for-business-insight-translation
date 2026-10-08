# Command line entry point for the vectorization step
#
# Run with:
# python -m src.vectorizing.cli

import argparse

from .embedder import DEFAULT_MODEL
from .pipeline import run_vectorizing


def main():

    parser = argparse.ArgumentParser(
        description="Convert retrieval chunks into embedding vectors"
    )

    parser.add_argument(
        "--input",
        default="data/chunks.parquet"
    )

    parser.add_argument(
        "--output-dir",
        default="data/vectorized"
    )

    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=32
    )

    args = parser.parse_args()

    run_vectorizing(
        input_path=args.input,
        output_dir=args.output_dir,
        model_name=args.model,
        batch_size=args.batch_size
    )


if __name__ == "__main__":
    main()