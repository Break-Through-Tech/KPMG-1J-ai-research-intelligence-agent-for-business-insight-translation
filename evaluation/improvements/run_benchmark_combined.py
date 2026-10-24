from pathlib import Path
import re

import numpy as np
import pandas as pd

from src.rag.retriever import ChromaRetriever


# Keep these settings fixed for the first comparison.
TOP_PAPERS = 5
CHUNK_POOL = 100
PAPER_CANDIDATES = 30
RRF_CONSTANT = 60

RESULTS_FOLDER = Path("evaluation/results")

OUTPUT_FILES = {
    "chunks_100": RESULTS_FOLDER / "retrieval_results_chunks_100.csv",
    "combined": RESULTS_FOLDER / "retrieval_results_combined.csv",
}


def base_id(paper_id):
    """Remove an arXiv version suffix, such as v1 or v2."""
    return re.sub(r"v\d+$", "", str(paper_id).strip())


def get_indexed_papers(collection):
    """Read indexed paper IDs in small batches."""
    indexed_papers = set()
    chunk_count = collection.count()

    for offset in range(0, chunk_count, 100):
        batch = collection.get(
            limit=100,
            offset=offset,
            include=["metadatas"],
        )

        for metadata in batch["metadatas"]:
            indexed_papers.add(base_id(metadata["paper_id"]))

    return indexed_papers


def combine_rankings(paper_ranking, chunk_ranking):
    """Combine two paper rankings using reciprocal rank fusion."""
    combined_scores = {}

    for ranking in [paper_ranking, chunk_ranking]:
        for rank, paper_id in enumerate(ranking, start=1):
            # Higher-ranked papers receive more points.
            # Papers found by both searches receive points from both.
            combined_scores[paper_id] = (
                combined_scores.get(paper_id, 0.0)
                + 1.0 / (RRF_CONSTANT + rank)
            )

    # Paper ID breaks score ties consistently.
    combined_ranking = sorted(
        combined_scores,
        key=lambda paper_id: (
            -combined_scores[paper_id],
            paper_id,
        ),
    )

    return combined_ranking, combined_scores


def make_result_rows(
    query,
    selected_papers,
    paper_details,
    chunk_details,
    paper_ranks,
    chunk_ranks,
    combined_scores=None,
):
    """Create spreadsheet rows for one query."""
    rows = []

    for rank, paper_id in enumerate(selected_papers, start=1):
        paper = paper_details[paper_id]
        chunk = chunk_details.get(paper_id, {})

        rows.append({
            "query_id": query["query_id"],
            "category": query["category"],
            "query": query["query"],
            "rank": rank,
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "abstract": paper["abstract"],
            "best_chunk_section": chunk.get("section", ""),
            "best_chunk_text": chunk.get("text", ""),
            "chunk_distance": chunk.get("distance"),
            "paper_search_rank": paper_ranks.get(paper_id),
            "chunk_search_rank": chunk_ranks.get(paper_id),
            "fusion_score": (
                combined_scores.get(paper_id)
                if combined_scores is not None else None
            ),
        })

    return rows


def add_existing_labels(results_df, baseline):
    """Reuse labels only for the same query and exact paper version."""
    labels = baseline[[
        "query_id",
        "paper_id",
        "relevance_label",
        "notes",
    ]]

    return results_df.merge(
        labels,
        on=["query_id", "paper_id"],
        how="left",
        validate="one_to_one",
    )


def main():
    # Protect results that may already contain manual labels.
    existing_files = [
        str(path)
        for path in OUTPUT_FILES.values()
        if path.exists()
    ]

    if existing_files:
        raise SystemExit(
            "These results files already exist. Rename them before "
            "running again:\n" + "\n".join(existing_files)
        )

    queries = pd.read_csv("evaluation/benchmark_queries.csv")
    papers = pd.read_parquet("data/papers_clean.parquet")
    baseline = pd.read_csv(
        RESULTS_FOLDER / "retrieval_results_baseline.csv"
    )

    if queries.empty or queries["query_id"].duplicated().any():
        raise SystemExit(
            "Benchmark queries must be nonempty with unique query IDs."
        )

    if baseline.duplicated(["query_id", "paper_id"]).any():
        raise SystemExit(
            "The baseline contains duplicate query–paper pairs."
        )

    retriever = ChromaRetriever()
    chunk_count = retriever.collection.count()

    if chunk_count == 0:
        raise SystemExit("The Chroma collection is empty.")

    indexed_papers = get_indexed_papers(retriever.collection)

    # Match corpus records to the papers represented in the index.
    papers = papers.copy()
    papers["base_id"] = papers["arxiv_id"].map(base_id)

    missing_papers = indexed_papers - set(papers["base_id"])

    if missing_papers:
        example_ids = ", ".join(sorted(missing_papers)[:10])
        raise SystemExit(
            f"{len(missing_papers)} indexed papers have no matching "
            f"record in papers_clean.parquet.\n"
            f"Examples: {example_ids}"
        )

    papers = papers[
        papers["base_id"].isin(indexed_papers)
    ].copy()

    # Avoid silently choosing between multiple corpus versions.
    if papers["base_id"].duplicated().any():
        raise SystemExit(
            "Multiple corpus records have the same base paper ID. "
            "Resolve those versions before running the experiment."
        )

    papers = papers.sort_values("base_id").reset_index(drop=True)

    papers["title"] = papers["title"].fillna("").astype(str)
    papers["abstract_clean"] = (
        papers["abstract_clean"].fillna("").astype(str)
    )

    paper_ids = papers["base_id"].tolist()
    paper_texts = (
        papers["title"] + "\n" + papers["abstract_clean"]
    ).tolist()

    paper_details = {
        row["base_id"]: {
            "paper_id": str(row["arxiv_id"]),
            "title": row["title"],
            "abstract": row["abstract_clean"],
        }
        for _, row in papers.iterrows()
    }

    print(f"\nIndexed chunks: {chunk_count}")
    print(f"Indexed papers: {len(papers)}")
    print("Embedding paper titles and abstracts...")

    # The existing embedder normalizes document and query vectors.
    # Their dot product therefore gives cosine similarity.
    paper_vectors = retriever.embedder.embed_documents(paper_texts)

    experiment_rows = {
        "chunks_100": [],
        "combined": [],
    }

    for _, query in queries.iterrows():
        query_text = query["query"]

        # SEARCH 1: compare the query with each title and abstract.
        query_vector = retriever.embedder.embed_query(query_text)
        similarities = paper_vectors @ query_vector

        top_paper_indices = np.argsort(
            -similarities,
            kind="stable",
        )[:PAPER_CANDIDATES]

        paper_ranking = [
            paper_ids[index] for index in top_paper_indices
        ]

        # SEARCH 2: use the existing chunk retriever.
        chunk_results = retriever.search(
            query_text,
            top_k=min(CHUNK_POOL, chunk_count),
        )

        # Sort explicitly by distance: lower means a closer match.
        chunk_matches = sorted(
            zip(
                chunk_results["documents"][0],
                chunk_results["metadatas"][0],
                chunk_results["distances"][0],
            ),
            key=lambda match: match[2],
        )

        chunk_details = {}

        for document, metadata, distance in chunk_matches:
            paper_id = base_id(metadata["paper_id"])

            # The first chunk encountered is the paper's best match.
            if paper_id not in chunk_details:
                chunk_details[paper_id] = {
                    "section": metadata.get("section", ""),
                    "text": document,
                    "distance": float(distance),
                }

        # Each search contributes up to 30 distinct paper candidates.
        chunk_ranking = list(chunk_details)[:PAPER_CANDIDATES]

        paper_ranks = {
            paper_id: rank
            for rank, paper_id in enumerate(paper_ranking, start=1)
        }
        chunk_ranks = {
            paper_id: rank
            for rank, paper_id in enumerate(chunk_ranking, start=1)
        }

        # CONTROL: larger chunk pool without title/abstract fusion.
        experiment_rows["chunks_100"].extend(
            make_result_rows(
                query=query,
                selected_papers=chunk_ranking[:TOP_PAPERS],
                paper_details=paper_details,
                chunk_details=chunk_details,
                paper_ranks=paper_ranks,
                chunk_ranks=chunk_ranks,
            )
        )

        # EXPERIMENT: combine title/abstract and chunk rankings.
        combined_ranking, combined_scores = combine_rankings(
            paper_ranking,
            chunk_ranking,
        )

        experiment_rows["combined"].extend(
            make_result_rows(
                query=query,
                selected_papers=combined_ranking[:TOP_PAPERS],
                paper_details=paper_details,
                chunk_details=chunk_details,
                paper_ranks=paper_ranks,
                chunk_ranks=chunk_ranks,
                combined_scores=combined_scores,
            )
        )

        print(
            f"Finished {query['query_id']}: "
            f"{len(chunk_details)} distinct papers in chunk pool"
        )

    RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)

    # Assemble both outputs before writing either file.
    result_tables = {}

    for experiment, rows in experiment_rows.items():
        results_df = pd.DataFrame(rows)
        result_tables[experiment] = add_existing_labels(
            results_df,
            baseline,
        )

    for experiment, results_df in result_tables.items():
        output_path = OUTPUT_FILES[experiment]
        results_df.to_csv(output_path, index=False)

        missing_labels = results_df["relevance_label"].isna().sum()

        print(f"\nSaved: {output_path}")
        print(f"Results: {len(results_df)}")
        print(f"Results needing labels: {missing_labels}")


if __name__ == "__main__":
    main()