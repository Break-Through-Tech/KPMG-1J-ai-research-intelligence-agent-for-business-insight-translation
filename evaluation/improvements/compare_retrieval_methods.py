from pathlib import Path
import re

import pandas as pd


RESULTS_FOLDER = Path("evaluation/results")
METHODS = ["baseline", "chunks_100", "combined"]
METRICS = ["precision", "strict_precision", "hit"]


def base_id(paper_id):
    """Remove arXiv version endings, such as v1 or v2."""
    return re.sub(r"v\d+$", "", str(paper_id).strip())


def score_method(method, queries):
    results = pd.read_csv(
        RESULTS_FOLDER / f"retrieval_results_{method}.csv"
    )

    # Check that every result has a valid relevance label.
    results["relevance_label"] = pd.to_numeric(
        results["relevance_label"], errors="coerce"
    )

    if not results["relevance_label"].isin([0, 1, 2]).all():
        raise ValueError(
            f"{method}: some relevance labels are missing or invalid."
        )

    if set(results["query_id"]) != set(queries["query_id"]):
        raise ValueError(
            f"{method}: query IDs do not match the benchmark."
        )

    if results.duplicated(["query_id", "paper_id"]).any():
        raise ValueError(f"{method}: duplicate query–paper pairs.")

    # Check that ranks start at 1 and contain at most five papers.
    results["rank"] = pd.to_numeric(
        results["rank"], errors="coerce"
    )

    for query_id, group in results.groupby("query_id"):
        ranks = sorted(group["rank"].dropna().tolist())
        expected_ranks = list(range(1, len(group) + 1))

        if not 1 <= len(group) <= 5 or ranks != expected_ranks:
            raise ValueError(
                f"{method}, {query_id}: invalid paper ranks."
            )

    # Same scoring rules as the original evaluation script.
    results["relevant"] = results["relevance_label"] >= 1
    results["highly_relevant"] = results["relevance_label"] == 2

    scores = results.groupby("query_id").agg(
        category=("category", "first"),
        papers_returned=("paper_id", "size"),
        precision=("relevant", "mean"),
        strict_precision=("highly_relevant", "mean"),
        hit=("relevant", "any"),
    ).reset_index()

    scores["hit"] = scores["hit"].astype(int)

    # Calculate the fraction of expected papers retrieved.
    target_recall = {}

    for _, query in queries.dropna(
        subset=["expected_paper_ids"]
    ).iterrows():
        expected = {
            base_id(paper_id)
            for paper_id in query["expected_paper_ids"].split(";")
        }

        retrieved = {
            base_id(paper_id)
            for paper_id in results.loc[
                results["query_id"] == query["query_id"],
                "paper_id",
            ]
        }

        target_recall[query["query_id"]] = (
            len(expected & retrieved) / len(expected)
        )

    # Retain the original scoring script's column name.
    scores["target_found"] = (
        scores["query_id"].map(target_recall)
    )
    scores.insert(0, "method", method)

    return scores


def main():
    queries = pd.read_csv("evaluation/benchmark_queries.csv")

    # Validate all three files before writing any scores.
    method_scores = [
        score_method(method, queries)
        for method in METHODS
    ]

    all_scores = pd.concat(method_scores, ignore_index=True)

    overall = all_scores.groupby("method", sort=False)[
        METRICS + ["target_found"]
    ].mean()

    by_category = all_scores.groupby(
        ["method", "category"], sort=False
    )[METRICS].mean()

    target_comparison = all_scores.pivot(
        index="query_id",
        columns="method",
        values="target_found",
    ).dropna(how="all").reindex(columns=METHODS)

    print("\n=== Overall comparison ===")
    print(overall.round(3).to_string())

    print("\n=== By category ===")
    print(by_category.round(3).to_string())

    print("\n=== Expected-paper recall by specific query ===")
    print(target_comparison.round(3).to_string())

    # Preserve the original baseline score file.
    for method, scores in zip(METHODS, method_scores):
        if method != "baseline":
            scores.to_csv(
                RESULTS_FOLDER / f"retrieval_scores_{method}.csv",
                index=False,
            )

    overall.to_csv(
        RESULTS_FOLDER / "retrieval_comparison_overall.csv"
    )
    by_category.to_csv(
        RESULTS_FOLDER / "retrieval_comparison_by_category.csv"
    )

    print("\nSaved new score files and comparison tables.")


if __name__ == "__main__":
    main()