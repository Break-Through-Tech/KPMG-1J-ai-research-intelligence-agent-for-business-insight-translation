from sentence_transformers import CrossEncoder

_model = None

def get_reranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"):
    global _model
    if _model is None:
        _model = CrossEncoder(model_name)
    return _model

def rerank(query: str, results: list[dict], text_key="text", top_k=5) -> list[dict]:
    if not results:
        return []
    reranker = get_reranker()
    pairs = [(query, r[text_key]) for r in results]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
    return [r for _, r in ranked[:top_k]]
