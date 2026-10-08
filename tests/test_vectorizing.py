import numpy as np
import pandas as pd
import pytest

from src.vectorizing.embedder import TextEmbedder
from src.vectorizing.pipeline import validate_chunks


def make_sample_chunks():
    """
    Small test dataset matching the real chunking output schema.
    """

    return pd.DataFrame([
        {
            "chunk_id": "2609.30264v1::0000",
            "paper_id": "2609.30264v1",
            "title": "Retrieval Augmented Generation",
            "authors": ["Test Author"],
            "arxiv_url": "https://arxiv.org/abs/2609.30264",
            "section": "1 Introduction",
            "section_type": "introduction",
            "section_id": "section_1",
            "source": "body",
            "chunk_index": 0,
            "n_chunks_in_paper": 2,
            "text": (
                "Retrieval augmented generation combines "
                "information retrieval with language models."
            ),
            "text_for_embedding": (
                "Retrieval Augmented Generation\n"
                "Section: 1 Introduction\n\n"
                "Retrieval augmented generation combines "
                "information retrieval with language models."
            ),
            "n_tokens": 20
        },
        {
            "chunk_id": "2609.30264v1::0001",
            "paper_id": "2609.30264v1",
            "title": "Retrieval Augmented Generation",
            "authors": ["Test Author"],
            "arxiv_url": "https://arxiv.org/abs/2609.30264",
            "section": "2 Methods",
            "section_type": "method",
            "section_id": "section_2",
            "source": "body",
            "chunk_index": 1,
            "n_chunks_in_paper": 2,
            "text": (
                "Dense embeddings represent text as vectors "
                "for semantic retrieval."
            ),
            "text_for_embedding": (
                "Retrieval Augmented Generation\n"
                "Section: 2 Methods\n\n"
                "Dense embeddings represent text as vectors "
                "for semantic retrieval."
            ),
            "n_tokens": 18
        }
    ])


def test_valid_chunk_schema():
    chunks = make_sample_chunks()

    # Should run without raising an exception
    validate_chunks(chunks)


def test_missing_required_column():
    chunks = make_sample_chunks()

    chunks = chunks.drop(
        columns=["text_for_embedding"]
    )

    with pytest.raises(ValueError):
        validate_chunks(chunks)


def test_duplicate_chunk_ids():
    chunks = make_sample_chunks()

    chunks.loc[1, "chunk_id"] = chunks.loc[0, "chunk_id"]

    with pytest.raises(ValueError):
        validate_chunks(chunks)


def test_document_embeddings():
    embedder = TextEmbedder()

    texts = [
        "Artificial intelligence can automate business processes.",
        "AI helps companies automate repetitive business tasks."
    ]

    embeddings = embedder.embed_documents(texts)

    assert embeddings.shape[0] == 2
    assert embeddings.shape[1] > 0


def test_embeddings_are_normalized():
    embedder = TextEmbedder()

    texts = [
        "Retrieval augmented generation uses external knowledge.",
        "Vector databases support semantic retrieval."
    ]

    embeddings = embedder.embed_documents(texts)

    norms = np.linalg.norm(
        embeddings,
        axis=1
    )

    assert np.allclose(
        norms,
        1.0,
        atol=1e-5
    )


def test_similar_text_is_closer():
    embedder = TextEmbedder()

    texts = [
        "Artificial intelligence can automate business processes.",
        "AI helps companies automate repetitive business tasks.",
        "Bananas are a fruit that contain potassium."
    ]

    embeddings = embedder.embed_documents(texts)

    similar_score = np.dot(
        embeddings[0],
        embeddings[1]
    )

    unrelated_score = np.dot(
        embeddings[0],
        embeddings[2]
    )

    assert similar_score > unrelated_score


def test_query_embedding():
    embedder = TextEmbedder()

    embedding = embedder.embed_query(
        "How can RAG help businesses?"
    )

    assert embedding.ndim == 1
    assert len(embedding) > 0

    norm = np.linalg.norm(embedding)

    assert np.isclose(
        norm,
        1.0,
        atol=1e-5
    )