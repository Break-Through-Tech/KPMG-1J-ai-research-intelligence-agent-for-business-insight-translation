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
            # Lists/arrays (for example, authors) must be checked FIRST.
            # pd.isna() on an array returns many True/False values at once,
            # which crashes with "truth value of an array is ambiguous".
            # Chroma can't store lists, so join them into one string.
            if isinstance(val, (list, tuple, np.ndarray)):
                meta_dict[col] = ", ".join(map(str, val))
            # Missing values become an empty string
            elif pd.isna(val):
                meta_dict[col] = ""
            # Turn numpy numbers into plain Python numbers
            elif isinstance(val, (np.integer, int)):
                meta_dict[col] = int(val)
            elif isinstance(val, (np.floating, float)):
                meta_dict[col] = float(val)
            # Anything else is stored as text
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
