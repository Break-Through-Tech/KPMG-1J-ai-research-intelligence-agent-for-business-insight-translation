import numpy as np

from src.vectorizing.embedder import TextEmbedder


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

def test_query_instruction_only_for_bge_queries():
    embedder = TextEmbedder()

    assert embedder.query_instruction.startswith("Represent this sentence")

    # the prefix changes the query vector, documents are embedded without it
    query = "How can RAG help businesses?"

    with_prefix = embedder.embed_query(query)
    without_prefix = embedder.embed_documents([query])[0]

    assert not np.allclose(with_prefix, without_prefix)


def test_count_truncated():
    embedder = TextEmbedder()

    short_text = "A short chunk."
    long_text = "word " * 2000

    assert embedder.count_truncated([short_text]) == 0
    assert embedder.count_truncated([short_text, long_text]) == 1
