# command line entrypoint for the chunking step
# ex: python -m src.chunking.cli --chunk-tokens 512 --overlap-tokens 64

import argparse

from .chunker import ChunkConfig
from .pipeline import run_chunking


def main():
    parser = argparse.ArgumentParser(description="split section rows into chunks with metadata")
    parser.add_argument("--input", default="data/chunk_input.jsonl")
    parser.add_argument("--output", default="data/chunks.parquet")
    parser.add_argument("--report", default="data/chunk_report.json")
    parser.add_argument("--chunk-tokens", type=int, default=512)
    parser.add_argument("--overlap-tokens", type=int, default=64)
    parser.add_argument("--min-section-tokens", type=int, default=30)
    # must match the embedding model, so chunks fit its 512-token limit; "none" uses the characters / 4 estimate
    parser.add_argument("--tokenizer", default="BAAI/bge-small-en-v1.5")
    args = parser.parse_args()

    cfg = ChunkConfig(chunk_tokens=args.chunk_tokens, overlap_tokens=args.overlap_tokens,
                      min_section_tokens=args.min_section_tokens,
                      tokenizer=None if args.tokenizer.lower() == "none" else args.tokenizer)
    run_chunking(input_path=args.input, output_path=args.output, report_path=args.report, cfg=cfg)


if __name__ == "__main__":
    main()
