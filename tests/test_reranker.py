from src.rag.reranker import rerank

def test_rerank_returns_top_k():
    results = [
        {"text": "LLMs are used in auditing to flag anomalies in financial records."},
        {"text": "The weather in Paris is mild in the spring."},
        {"text": "Large language models help auditors review contracts faster."},
        {"text": "Photosynthesis converts sunlight into energy in plants."},
        {"text": "AI tools assist in detecting fraud patterns during audits."},
    ]
    reranked = rerank("how are LLMs used in auditing?", results, top_k=3)
    assert len(reranked) == 3

def test_rerank_puts_relevant_results_first():
    results = [
        {"text": "The weather in Paris is mild in the spring."},
        {"text": "LLMs are used in auditing to flag anomalies in financial records."},
    ]
    reranked = rerank("how are LLMs used in auditing?", results, top_k=2)
    # the relevant result should be ranked first
    assert "LLMs" in reranked[0]["text"] or "auditing" in reranked[0]["text"]

def test_rerank_empty_input_returns_empty():
    assert rerank("any query", []) == []
