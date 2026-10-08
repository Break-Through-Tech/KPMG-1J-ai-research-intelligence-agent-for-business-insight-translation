"""
===============================================================================
Indexer Module (src/rag/indexer.py)
===============================================================================

Purpose:
  Loads pre-computed vector embeddings (.npy) and chunk metadata (.parquet) from 
  the vectorization pipeline, cleans metadata formats, and upserts them into a 
  persistent ChromaDB collection.

Key Function:
  - build_chroma_index(...): Processes vector files and stores embeddings.
===============================================================================
"""

from pathlib import Path
import chromadb
import numpy as np
import pandas as pd


def build_chroma_index(
    embeddings_path: str = "data/vectorized/embeddings.npy",
    metadata_path: str = "data/vectorized/chunk_metadata.parquet",
    db_dir: str = "data/chroma_db",
    collection_name: str = "kpmg_research_collection"
):
    emb_file = Path(embeddings_path)
    meta_file = Path(metadata_path)

    if not emb_file.exists() or not meta_file.exists():
        raise FileNotFoundError(
            f"Vectorization outputs not found! Checked '{embeddings_path}' and '{metadata_path}'."
        )

    embeddings = np.load(emb_file)
    df = pd.read_parquet(meta_file)

    if len(embeddings) != len(df):
        raise ValueError(f"Mismatch: {len(embeddings)} embeddings vs {len(df)} metadata rows.")

    client = chromadb.PersistentClient(path=db_dir)
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"}
    )

    ids = df["chunk_id"].astype(str).tolist()
    documents = df["text"].astype(str).tolist()
    metadata_df = df.drop(columns=["text"])
    
    metadatas = []
    for _, row in metadata_df.iterrows():
        meta_dict = {}
        for col, val in row.items():
            if pd.isna(val):
                meta_dict[col] = ""
            elif isinstance(val, (np.integer, int)):
                meta_dict[col] = int(val)
            elif isinstance(val, (np.floating, float)):
                meta_dict[col] = float(val)
            else:
                meta_dict[col] = str(val)
        metadatas.append(meta_dict)

    batch_size = 500
    for i in range(0, len(ids), batch_size):
        end_idx = i + batch_size
        collection.upsert(
            ids=ids[i:end_idx],
            embeddings=embeddings[i:end_idx].tolist(),
            documents=documents[i:end_idx],
            metadatas=metadatas[i:end_idx]
        )
    
    return len(ids)


if __name__ == "__main__":
    print("--- Testing Chroma Indexer ---")
    try:
        total_indexed = build_chroma_index()
        print(f"Successfully indexed {total_indexed} items into ChromaDB.")
    except Exception as e:
        print(f"Error during indexing: {e}")
