from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.rag.query_rewriter import rewrite_query


DEFAULT_BENCHMARK = Path("data/evaluation/benchmark_questions.csv")
DEFAULT_OUTPUT = Path("data/evaluation/retrieval_comparison.csv")


@dataclass
class RankedPaper:
    rank: int
    paper_id: str
    title: str
    distance: float | None


def normalize_arxiv_id(value: str) -> str:
    value = (value or "").strip()
    value = value.removeprefix("arXiv:")
    value = value.replace("https://arxiv.org/abs/", "")
    value = value.replace("http://arxiv.org/abs/", "")
    return re.sub(r"v\d+$", "", value)


def parse_expected_ids(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def load_benchmarks(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError(f"No benchmark rows found in {path}")

    return rows


def distinct_papers_from_chroma_result(
    result: dict[str, Any],
    top_papers: int = 5,
) -> list[RankedPaper]:
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]

    papers: list[RankedPaper] = []
    seen: set[str] = set()

    # Chroma returns chunks, so keep only the first ranked chunk from each paper.
    for idx, metadata in enumerate(metadatas):
        metadata = metadata or {}
        paper_id = str(metadata.get("paper_id", "")).strip()

        if not paper_id:
            continue

        normalized = normalize_arxiv_id(paper_id)

        if normalized in seen:
            continue

        seen.add(normalized)
        distance = distances[idx] if idx < len(distances) else None

        papers.append(
            RankedPaper(
                rank=len(papers) + 1,
                paper_id=paper_id,
                title=str(metadata.get("title", "")),
                distance=float(distance) if distance is not None else None,
            )
        )

        if len(papers) >= top_papers:
            break

    return papers


def retrieve_top_papers(
    retriever: Any,
    query: str,
    top_papers: int = 5,
) -> list[RankedPaper]:
    # Retrieve extra chunks so there are enough distinct papers for Top-5.
    chunk_k = max(top_papers * 5, top_papers)
    result = retriever.search(query, top_k=chunk_k)

    return distinct_papers_from_chroma_result(
        result,
        top_papers=top_papers,
    )


def evaluate_hit(
    expected_ids: list[str],
    papers: list[RankedPaper],
) -> tuple[bool, bool, list[str]]:
    expected = {
        normalize_arxiv_id(paper_id)
        for paper_id in expected_ids
    }
    retrieved = {
        normalize_arxiv_id(paper.paper_id)
        for paper in papers
    }

    matched = sorted(expected & retrieved)

    return bool(matched), expected.issubset(retrieved), matched


def run_benchmark(
    retriever: Any,
    benchmark_path: Path = DEFAULT_BENCHMARK,
    output_path: Path = DEFAULT_OUTPUT,
    top_papers: int = 5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for benchmark in load_benchmarks(benchmark_path):
        question = benchmark["business_question"]
        expected_ids = parse_expected_ids(
            benchmark["expected_paper_ids"]
        )

        # Run the same benchmark with the original and rewritten query.
        for query_type, query in (
            ("original", question),
            ("rewritten", rewrite_query(question)),
        ):
            papers = retrieve_top_papers(
                retriever,
                query,
                top_papers=top_papers,
            )

            hit_any, hit_all, matched = evaluate_hit(
                expected_ids,
                papers,
            )

            rows.append(
                {
                    "question_id": benchmark["question_id"],
                    "query_type": query_type,
                    "query": query,
                    "expected_paper_ids": ";".join(expected_ids),
                    "retrieved_top_5_paper_ids": ";".join(
                        paper.paper_id for paper in papers
                    ),
                    "retrieved_top_5_titles": " || ".join(
                        paper.title for paper in papers
                    ),
                    "matched_expected_ids": ";".join(matched),
                    "hit_any_at_5": int(hit_any),
                    "hit_all_at_5": int(hit_all),
                }
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    print_summary(rows)
    print(f"\nSaved comparison to: {output_path}")

    return rows


def _hit_rate(
    rows: list[dict[str, Any]],
    query_type: str,
) -> float:
    selected = [
        row
        for row in rows
        if row["query_type"] == query_type
    ]

    if not selected:
        return 0.0

    return (
        sum(int(row["hit_any_at_5"]) for row in selected)
        / len(selected)
    )


def print_summary(rows: list[dict[str, Any]]) -> None:
    original = _hit_rate(rows, "original")
    rewritten = _hit_rate(rows, "rewritten")

    print("\n=== Abdullah Task #1: Retrieval Comparison ===")
    print(f"Original query Hit@5 : {original:.1%}")
    print(f"Rewritten query Hit@5: {rewritten:.1%}")
    print(f"Change                : {rewritten - original:+.1%}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-dir", default="data/chroma_db")
    parser.add_argument(
        "--collection",
        default="kpmg_research_collection",
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_BENCHMARK,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )

    args = parser.parse_args()

    # Import only when running the benchmark so helper functions stay testable.
    from src.rag.retriever import ChromaRetriever

    retriever = ChromaRetriever(
        db_dir=args.db_dir,
        collection_name=args.collection,
    )

    run_benchmark(
        retriever,
        benchmark_path=args.benchmark,
        output_path=args.output,
        top_papers=5,
    )


if __name__ == "__main__":
    main()
