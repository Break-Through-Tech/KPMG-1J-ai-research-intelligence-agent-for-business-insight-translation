# Vectorization pipeline:
# data/chunks.parquet -> embeddings + chunk metadata

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .embedder import DEFAULT_MODEL, TextEmbedder


# These columns are required from the chunking pipeline
REQUIRED_COLUMNS = [
    "chunk_id",
    "paper_id",
    "version",
    "title",
    "published_date",
    "primary_category",
    "section",
    "text",
    "text_for_embedding"
]


def validate_chunks(chunks):
    """
    Validate the chunking output before creating embeddings.
    """

    missing_columns = []

    for column in REQUIRED_COLUMNS:
        if column not in chunks.columns:
            missing_columns.append(column)

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing_columns)
        )

    if len(chunks) == 0:
        raise ValueError("No chunks found in input file")

    if chunks["chunk_id"].isna().any():
        raise ValueError("Some chunks are missing chunk_id")

    if chunks["chunk_id"].duplicated().any():
        duplicate_count = int(
            chunks["chunk_id"].duplicated().sum()
        )

        raise ValueError(
            f"Found {duplicate_count} duplicate chunk IDs"
        )

    if chunks["text_for_embedding"].isna().any():
        raise ValueError(
            "Some chunks are missing text_for_embedding"
        )

    empty_text = (
        chunks["text_for_embedding"]
        .astype(str)
        .str.strip()
        .eq("")
    )

    if empty_text.any():
        raise ValueError(
            f"Found {int(empty_text.sum())} empty texts for embedding"
        )


def run_vectorizing(
    input_path="data/chunks.parquet",
    output_dir="data/vectorized",
    model_name=DEFAULT_MODEL,
    batch_size=32
):
    """
    Read chunks, create normalized embeddings,
    and save vectors + metadata.
    """

    input_file = Path(input_path)

    if not input_file.exists():
        raise FileNotFoundError(
            f"{input_path} not found. "
            "Run the chunking pipeline first or obtain chunks.parquet."
        )

    print(f"Reading chunks from {input_path}")

    chunks = pd.read_parquet(input_file)

    print(f"Loaded {len(chunks):,} chunks")

    validate_chunks(chunks)

    # Reset the index so row i in metadata always corresponds
    # exactly to row i in the embedding matrix.
    chunks = chunks.reset_index(drop=True)

    # Alena's chunking pipeline already creates this field as:
    #
    # title
    # Section: section name
    #
    # chunk text
    #
    # We embed this rather than rebuilding the text here.
    texts = (
        chunks["text_for_embedding"]
        .astype(str)
        .tolist()
    )

    embedder = TextEmbedder(
        model_name=model_name,
        batch_size=batch_size
    )

    # The model silently drops anything past max_seq_length,
    # so report how often that happens.
    n_truncated = embedder.count_truncated(texts)

    if n_truncated:
        print(
            f"Warning: {n_truncated:,} chunks are longer than "
            f"{embedder.model.max_seq_length} tokens and will be truncated"
        )

    print(f"Embedding {len(texts):,} chunks")

    embeddings = embedder.embed_documents(texts)

    # Every chunk must produce exactly one embedding.
    if len(embeddings) != len(chunks):
        raise RuntimeError(
            "Number of embeddings does not match number of chunks"
        )

    # Make sure the model did not produce invalid values.
    if not np.isfinite(embeddings).all():
        raise RuntimeError(
            "Embeddings contain NaN or infinite values"
        )

    output = Path(output_dir)

    output.mkdir(
        parents=True,
        exist_ok=True
    )

    embedding_path = output / "embeddings.npy"
    metadata_path = output / "chunk_metadata.parquet"
    report_path = output / "embedding_report.json"

    # Save the numerical embedding matrix.
    #
    # embeddings[i] corresponds to metadata row i.
    np.save(
        embedding_path,
        embeddings
    )

    # Preserve all original metadata from chunking.
    # This includes paper title, authors, arXiv URL,
    # section information, and original text.
    chunks.to_parquet(
        metadata_path,
        index=False
    )

    # Since normalize_embeddings=True, each vector
    # should have a norm very close to 1.
    norms = np.linalg.norm(
        embeddings,
        axis=1
    )

    report = {
        "model_name": model_name,
        "chunks_embedded": int(len(chunks)),
        "embedding_dimension": int(embeddings.shape[1]),
        "embedding_dtype": str(embeddings.dtype),
        "max_seq_length": int(embedder.model.max_seq_length),
        "chunks_truncated": int(n_truncated),
        "query_instruction": embedder.query_instruction,
        "normalized": True,
        "mean_vector_norm": float(norms.mean()),
        "min_vector_norm": float(norms.min()),
        "max_vector_norm": float(norms.max()),
        "input_path": str(input_file),
        "embeddings_path": str(embedding_path),
        "metadata_path": str(metadata_path)
    }

    with open(
        report_path,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            report,
            file,
            indent=2
        )

    print()
    print("Vectorization complete")
    print(f"Chunks embedded: {len(chunks):,}")
    print(f"Embedding shape: {embeddings.shape}")
    print(f"Mean vector norm: {norms.mean():.4f}")
    print(f"Embeddings saved to: {embedding_path}")
    print(f"Metadata saved to: {metadata_path}")
    print(f"Report saved to: {report_path}")

    return embeddings, chunks