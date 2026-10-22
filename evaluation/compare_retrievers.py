# Compare retrievers on the benchmark questions, without calling an LLM
#
# Methods:
#   chroma-combined  Thania's CombinedRetriever on the local Chroma database (old baseline)
#   lance            Grace's LanceDB hybrid chunk search, grouped into papers
#   lance-combined   Thania's method (title/abstract + chunk search, RRF) on LanceDB
#
# Run from the project root:
# python -m evaluation.compare_retrievers --papers data/release/papers_clean.parquet

import argparse
import time
from itertools import combinations
from pathlib import Path

import pandas as pd

from src.rag.lance_retriever import base_id


RESULTS_FOLDER = Path("evaluation/results")

# Papers that showed up in many unrelated end-to-end answers
RECURRING_PAPERS = ["2610.09371", "2610.05532", "2610.15136"]


def load_queries(benchmark_path, business_path):
    """
    The 25 benchmark queries plus Abdullah's 6 business questions.
    Abdullah's questions are rewordings of Q10-Q15 with the same expected papers.
    """
    queries = pd.read_csv(benchmark_path)

    business = pd.read_csv(business_path).rename(columns={
        "question_id": "query_id",
        "business_question": "query",
    })
    business["query_id"] = "B" + business["query_id"].str.lstrip("Q").str.zfill(2)
    business["category"] = "business-specific"

    columns = ["query_id", "category", "query", "expected_paper_ids"]

    return pd.concat([queries[columns], business[columns]], ignore_index=True)


def expected_ids(value):
    if pd.isna(value) or not str(value).strip():
        return set()

    return {base_id(paper_id) for paper_id in str(value).split(";") if paper_id.strip()}


def load_labels(path):
    """Thania's 0/1/2 relevance labels, keyed by (query_id, base paper ID)."""
    if not Path(path).exists():
        return {}

    labels = pd.read_csv(path)

    return {
        (row.query_id, base_id(row.paper_id)): row.relevance_label
        for row in labels.itertuples()
    }


def build_retrievers(methods, papers_path, index_dir, chroma_dir):
    # Imported here so each method only needs its own database
    retrievers = {}

    for method in methods:
        print(f"Loading {method}...")

        if method == "chroma-combined":
            from src.rag.combined_retriever import CombinedRetriever
            retrievers[method] = CombinedRetriever(papers_path=papers_path, db_dir=chroma_dir)

        elif method == "lance":
            from src.rag.lance_retriever import LanceRetriever
            retrievers[method] = LanceRetriever(papers_path=papers_path, index_dir=index_dir)

        elif method == "lance-combined":
            from src.rag.lance_retriever import LanceCombinedRetriever
            retrievers[method] = LanceCombinedRetriever(papers_path=papers_path, index_dir=index_dir)

        else:
            raise ValueError(f"Unknown method: {method}")

    return retrievers


def run_queries(retrievers, queries, labels, top_k):
    rows = []

    for method, retriever in retrievers.items():
        for query in queries.itertuples():
            start = time.perf_counter()
            results = retriever.search(query.query, top_k=top_k)
            seconds = time.perf_counter() - start

            for rank, paper in enumerate(results, start=1):
                paper_id = base_id(paper["paper_id"])

                rows.append({
                    "method": method,
                    "query_id": query.query_id,
                    "category": query.category,
                    "query": query.query,
                    "rank": rank,
                    "paper_id": paper["paper_id"],
                    "title": paper["title"],
                    "best_chunk_section": paper.get("best_chunk_section", ""),
                    "is_expected": paper_id in expected_ids(query.expected_paper_ids),
                    "seconds": seconds,
                    "relevance_label": labels.get((query.query_id, paper_id)),
                })

    return pd.DataFrame(rows)


def known_item_test(retrievers, papers_path, sample_size, top_k, seed=42):
    """
    Search each sampled paper's title and record where that paper ranks.
    Only papers every retriever has indexed are sampled.
    """
    indexed = None

    for retriever in retrievers.values():
        ids = set(retriever.papers.index)
        indexed = ids if indexed is None else indexed & ids

    papers = pd.read_parquet(papers_path, columns=["arxiv_id", "title"])
    papers["base_id"] = papers["arxiv_id"].map(base_id)
    papers = papers[papers["base_id"].isin(indexed)].drop_duplicates("base_id")

    sample = papers.sample(n=min(sample_size, len(papers)), random_state=seed)

    rows = []

    for method, retriever in retrievers.items():
        for paper in sample.itertuples():
            results = retriever.search(paper.title, top_k=top_k)
            found = [base_id(result["paper_id"]) for result in results]

            rank = found.index(paper.base_id) + 1 if paper.base_id in found else None

            rows.append({"method": method, "paper_id": paper.base_id, "rank": rank})

    return pd.DataFrame(rows)


def summarize(results, known_items, queries):
    target_queries = queries[queries["expected_paper_ids"].map(expected_ids).map(bool)]

    summary = []

    for method, group in results.groupby("method", sort=False):
        targets = group[group["query_id"].isin(target_queries["query_id"])]

        hits, recalls, reciprocal_ranks = [], [], []

        for query in target_queries.itertuples():
            expected = expected_ids(query.expected_paper_ids)
            found = targets[targets["query_id"] == query.query_id]
            found_ids = [base_id(paper_id) for paper_id in found.sort_values("rank")["paper_id"]]

            matches = [rank for rank, paper_id in enumerate(found_ids, start=1) if paper_id in expected]

            hits.append(bool(matches))
            recalls.append(len(set(found_ids) & expected) / len(expected))
            reciprocal_ranks.append(1 / matches[0] if matches else 0.0)

        known = known_items[known_items["method"] == method]

        labelled = group.dropna(subset=["relevance_label"])

        summary.append({
            "method": method,
            "target_queries": len(target_queries),
            "target_hit_rate": sum(hits) / len(hits),
            "target_recall_at_5": sum(recalls) / len(recalls),
            "target_mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
            "known_item_papers": len(known),
            "known_item_hit_at_5": known["rank"].notna().mean() if len(known) else None,
            "known_item_mrr": (1 / known["rank"]).fillna(0).mean() if len(known) else None,
            "recurring_paper_appearances": int(
                group["paper_id"].map(base_id).isin(RECURRING_PAPERS).sum()
            ),
            "distinct_papers_returned": group["paper_id"].map(base_id).nunique(),
            "labelled_rows": f"{len(labelled)}/{len(group)}",
            "labelled_precision": (labelled["relevance_label"] >= 1).mean() if len(labelled) else None,
            "labelled_strict_precision": (labelled["relevance_label"] == 2).mean() if len(labelled) else None,
            "seconds_per_query": group.drop_duplicates("query_id")["seconds"].mean(),
        })

    return pd.DataFrame(summary)


def overlap(results):
    """Average Jaccard overlap of each pair of methods' top results, per query."""
    top_sets = {
        (method, query_id): set(group["paper_id"].map(base_id))
        for (method, query_id), group in results.groupby(["method", "query_id"])
    }

    methods = list(dict.fromkeys(results["method"]))
    query_ids = list(dict.fromkeys(results["query_id"]))

    rows = []

    for first, second in combinations(methods, 2):
        scores = []

        for query_id in query_ids:
            a = top_sets.get((first, query_id), set())
            b = top_sets.get((second, query_id), set())
            scores.append(len(a & b) / len(a | b) if a | b else 1.0)

        rows.append({"method_a": first, "method_b": second, "mean_jaccard": sum(scores) / len(scores)})

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description="Compare retrievers on the benchmark questions")
    parser.add_argument("--papers", default="data/papers_clean.parquet")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--chroma-dir", default="data/chroma_db")
    parser.add_argument("--benchmark", default="evaluation/benchmark_queries.csv")
    parser.add_argument("--business", default="src/benchmark_questions.csv")
    parser.add_argument("--labels", default="evaluation/results/thania_relevance_labels.csv")
    parser.add_argument("--methods", nargs="+", default=["chroma-combined", "lance", "lance-combined"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--known-items", type=int, default=100,
                        help="number of papers for the title search test (0 to skip)")
    parser.add_argument("--output-dir", default=str(RESULTS_FOLDER))
    args = parser.parse_args()

    queries = load_queries(args.benchmark, args.business)
    labels = load_labels(args.labels)

    retrievers = build_retrievers(args.methods, args.papers, args.index_dir, args.chroma_dir)

    print(f"Running {len(queries)} queries with {len(retrievers)} retrievers...")
    results = run_queries(retrievers, queries, labels, args.top_k)

    if args.known_items:
        print(f"Running the title search test on {args.known_items} papers...")
        known_items = known_item_test(retrievers, args.papers, args.known_items, args.top_k)
    else:
        known_items = pd.DataFrame(columns=["method", "paper_id", "rank"])

    summary = summarize(results, known_items, queries)
    pair_overlap = overlap(results)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results.to_csv(output_dir / "retriever_comparison_results.csv", index=False)
    summary.to_csv(output_dir / "retriever_comparison_summary.csv", index=False)
    pair_overlap.to_csv(output_dir / "retriever_comparison_overlap.csv", index=False)
    known_items.to_csv(output_dir / "retriever_comparison_known_items.csv", index=False)

    with pd.option_context("display.width", 200, "display.max_columns", None):
        print("\n" + summary.round(3).to_string(index=False))
        print("\n" + pair_overlap.round(3).to_string(index=False))

    print(f"\nSaved results to {output_dir}")


if __name__ == "__main__":
    main()
