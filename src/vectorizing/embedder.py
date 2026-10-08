# Creates embedding vectors from the chunks produced by the chunking pipeline

from sentence_transformers import SentenceTransformer
import numpy as np


# Baseline embedding model
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class TextEmbedder:

    def __init__(self, model_name=DEFAULT_MODEL, batch_size=32):
        self.model_name = model_name
        self.batch_size = batch_size

        print(f"Loading embedding model: {model_name}")

        self.model = SentenceTransformer(model_name)

    def embed_documents(self, texts):
        """
        Convert chunk text into normalized embedding vectors.
        """

        if len(texts) == 0:
            return np.empty((0, 0), dtype=np.float32)

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            normalize_embeddings=True,
            convert_to_numpy=True
        )

        return embeddings.astype(np.float32)

    def embed_query(self, query):
        """
        Convert a user query into an embedding using the same model.
        """

        if not query.strip():
            raise ValueError("Query cannot be empty")

        embedding = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True
        )[0]

        return embedding.astype(np.float32)