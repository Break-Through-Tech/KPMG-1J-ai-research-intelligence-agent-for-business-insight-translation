import pandas as pd
from src.rag.retriever import ChromaRetriever

TOP_PAPERS = 5       # papers to label per query
CHUNK_POOL = 30      # chunks to search before grouping into papers

queries = pd.read_csv("evaluation/benchmark_queries.csv")
papers = pd.read_parquet("data/papers_clean.parquet")
abstracts = papers.set_index("arxiv_id")["abstract_clean"].to_dict()

retriever = ChromaRetriever()
rows = []

for _, q in queries.iterrows():
    res = retriever.search(q["query"], top_k=CHUNK_POOL)
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    # keep the best (lowest-distance) chunk for each paper, in rank order
    seen = {}
    for doc, meta, dist in zip(docs, metas, dists):
        pid = meta["paper_id"]
        if pid not in seen:
            seen[pid] = {"title": meta["title"], "distance": dist,
                         "section": meta.get("section", ""), "chunk": doc}

    for rank, (pid, info) in enumerate(list(seen.items())[:TOP_PAPERS], start=1):
        rows.append({
            "query_id": q["query_id"],
            "category": q["category"],
            "query": q["query"],
            "rank": rank,
            "paper_id": pid,
            "title": info["title"],
            "distance": round(info["distance"], 4),
            "abstract": str(abstracts.get(pid, ""))[:600],
            "best_chunk_section": info["section"],
            "best_chunk_text": info["chunk"][:400],
            "relevance_label": "",
            "notes": "",
        })

out = pd.DataFrame(rows)
out.to_csv("evaluation/results/retrieval_results_baseline.csv", index=False)
print(f"Saved {len(out)} rows for {out['query_id'].nunique()} queries")