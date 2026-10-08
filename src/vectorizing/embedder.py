# Creates embedding vectors from the chunks produced by the chunking pipeline

from sentence_transformers import SentenceTransformer
import numpy as np


# Baseline embedding model
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# bge models retrieve better when short queries (not documents) get this prefix
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class TextEmbedder:

    def __init__(self, model_name=DEFAULT_MODEL, batch_size=32, use_query_instruction=True):
        self.model_name = model_name
        self.batch_size = batch_size

        # only queries get the prefix, chunk text is embedded as is
        self.query_instruction = (
            BGE_QUERY_INSTRUCTION
            if use_query_instruction and "bge" in model_name.lower()
            else ""
        )

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

    def count_truncated(self, texts):
        """
        Count texts longer than the model's max_seq_length.
        The model silently drops everything past that limit.
        """

        token_lengths = [
            len(ids)
            for ids in self.model.tokenizer(
                list(texts),
                add_special_tokens=True
            )["input_ids"]
        ]

        return sum(
            n > self.model.max_seq_length
            for n in token_lengths
        )

    def embed_query(self, query):
        """
        Convert a user query into an embedding using the same model.
        """

        if not query.strip():
            raise ValueError("Query cannot be empty")

        embedding = self.model.encode(
            [self.query_instruction + query],
            normalize_embeddings=True,
            convert_to_numpy=True
        )[0]

        return embedding.astype(np.float32)