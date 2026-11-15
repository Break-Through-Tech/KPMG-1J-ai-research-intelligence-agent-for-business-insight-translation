import pandas as pd

# Load the labeled results and the benchmark queries
df = pd.read_csv("evaluation/results/retrieval_results_baseline.csv")
queries = pd.read_csv("evaluation/benchmark_queries.csv")

# Stop if any rows are still unlabeled
if df["relevance_label"].isna().any():
    raise SystemExit("Some rows still have no relevance_label. Finish labeling first.")

# Flag each paper: relevant = labeled 1 or 2, highly relevant = labeled 2
df["relevant"] = df["relevance_label"] >= 1
df["highly_relevant"] = df["relevance_label"] == 2

# Score each query
per_query = df.groupby("query_id").agg(
    category=("category", "first"),
    precision=("relevant", "mean"),             # share of papers that are relevant
    strict_precision=("highly_relevant", "mean"),  # share that are highly relevant
    hit=("relevant", "any"),                    # did we find at least one relevant paper?
).reset_index()
per_query["hit"] = per_query["hit"].astype(int)

# Check whether the known target paper was found (specific queries only).
# Version suffixes (v1, v2) are stripped so 2609.38036v2 matches 2609.38036v1.
def base_id(paper_id):
    return paper_id.split("v")[0]

targets = queries.dropna(subset=["expected_paper_ids"])
found = {}
for _, row in targets.iterrows():
    expected = {base_id(p) for p in row["expected_paper_ids"].split(";")}
    retrieved = {base_id(p) for p in df[df["query_id"] == row["query_id"]]["paper_id"]}
    found[row["query_id"]] = len(expected & retrieved) / len(expected)
per_query["target_found"] = per_query["query_id"].map(found)

# Print results
print("\n=== Overall ===")
print(per_query[["precision", "strict_precision", "hit"]].mean().round(2).to_string())

print("\n=== By category ===")
print(per_query.groupby("category")[["precision", "strict_precision", "hit"]].mean().round(2).to_string())

print("\n=== Target paper found (specific queries) ===")
print(per_query.dropna(subset=["target_found"])[["query_id", "target_found"]].to_string(index=False))

print("\n=== 5 weakest queries ===")
print(per_query.sort_values("precision").head(5)[["query_id", "category", "precision"]].to_string(index=False))

per_query.to_csv("evaluation/results/retrieval_scores_baseline.csv", index=False)
print("\nSaved evaluation/results/retrieval_scores_baseline.csv")