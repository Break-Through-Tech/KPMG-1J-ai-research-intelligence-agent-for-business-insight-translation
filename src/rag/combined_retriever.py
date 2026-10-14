import re

import numpy as np
import pandas as pd

from src.rag.retriever import ChromaRetriever


def base_id(paper_id):
    """Treat arXiv versions such as v1 and v2 as the same paper."""
    return re.sub(r"v\d+$", "", str(paper_id).strip())


class CombinedRetriever:
    """
    1. Search paper titles and abstracts.
    2. Search chunks and group them by paper.
    3. Combine both rankings.
    4. Return papers with a supporting chunk.
    """

    def __init__(
        self,
        papers_path="data/papers_clean.parquet",
        db_dir="data/chroma_db",
        collection_name="kpmg_research_collection",
    ):
        # Same settings used in the combined benchmark.
        self.chunk_pool = 100
        self.paper_candidates = 30
        self.rrf_constant = 60

        self.base = ChromaRetriever(
            db_dir=db_dir,
            collection_name=collection_name,
        )
        self.collection = self.base.collection
        self.embedder = self.base.embedder
        self.chunk_count = self.collection.count()

        if self.chunk_count == 0:
            raise ValueError("The Chroma collection is empty.")

        self.indexed_versions = self._get_indexed_versions()
        self.papers = self._load_papers(papers_path)
        self.paper_ids = self.papers.index.tolist()

        texts = (
            self.papers["title"]
            + "\n"
            + self.papers["abstract_clean"]
        ).tolist()

        # Computed once when the retriever is initialized.
        self.paper_vectors = self.embedder.embed_documents(texts)

    def _get_indexed_versions(self):
        """Map each base paper ID to its actual IDs in Chroma."""
        versions = {}

        # Small batches avoid the SQL-variable error seen earlier.
        for offset in range(0, self.chunk_count, 100):
            batch = self.collection.get(
                limit=100,
                offset=offset,
                include=["metadatas"],
            )

            for metadata in batch["metadatas"]:
                actual_id = str(metadata["paper_id"])
                paper_id = base_id(actual_id)
                versions.setdefault(paper_id, set()).add(actual_id)

        return versions

    def _load_papers(self, papers_path):
        """Load metadata for papers represented in the database."""
        papers = pd.read_parquet(papers_path)
        papers["base_id"] = papers["arxiv_id"].map(base_id)

        missing = set(self.indexed_versions) - set(papers["base_id"])

        if missing:
            raise ValueError(
                f"{len(missing)} indexed papers are missing "
                "from papers_clean.parquet."
            )

        papers = papers[
            papers["base_id"].isin(self.indexed_versions)
        ].copy()

        if papers["base_id"].duplicated().any():
            raise ValueError(
                "Multiple corpus records share the same base paper ID."
            )

        papers["title"] = papers["title"].fillna("").astype(str)
        papers["abstract_clean"] = (
            papers["abstract_clean"].fillna("").astype(str)
        )

        return papers.set_index("base_id").sort_index()

    def _rank_papers(self, query_vector):
        """Rank papers by title/abstract cosine similarity."""
        similarities = self.paper_vectors @ query_vector

        positions = np.argsort(
            -similarities, kind="stable"
        )[:self.paper_candidates]

        return [self.paper_ids[position] for position in positions]

    def _rank_chunks(self, query_vector):
        """Rank distinct papers using their best matching chunk."""
        results = self.collection.query(
            query_embeddings=[query_vector.tolist()],
            n_results=min(self.chunk_pool, self.chunk_count),
            include=["metadatas", "distances"],
        )

        matches = sorted(
            zip(
                results["metadatas"][0],
                results["distances"][0],
            ),
            key=lambda match: match[1],
        )

        # Keep each paper's first occurrence: its lowest-distance chunk.
        paper_ids = [
            base_id(metadata["paper_id"])
            for metadata, distance in matches
        ]

        return list(dict.fromkeys(paper_ids))[:self.paper_candidates]

    def _combine_rankings(self, paper_ranking, chunk_ranking):
        """Give papers points based on their position in both lists."""
        scores = {}

        for ranking in [paper_ranking, chunk_ranking]:
            for rank, paper_id in enumerate(ranking, start=1):
                # Higher ranks earn more points.
                # Appearing in both lists earns points from both.
                scores[paper_id] = (
                    scores.get(paper_id, 0.0)
                    + 1.0 / (self.rrf_constant + rank)
                )

        ranking = sorted(
            scores,
            key=lambda paper_id: (-scores[paper_id], paper_id),
        )

        return ranking, scores

    def _get_evidence(self, paper_id, query_vector):
        """Find the closest chunk within one selected paper."""
        results = self.collection.query(
            query_embeddings=[query_vector.tolist()],
            n_results=1,
            where={
                "paper_id": {
                    "$in": sorted(self.indexed_versions[paper_id])
                }
            },
            include=["documents", "metadatas", "distances"],
        )

        if not results["documents"][0]:
            raise RuntimeError(
                f"No supporting chunk found for {paper_id}."
            )

        metadata = results["metadatas"][0][0]

        return {
            "chunk_id": results["ids"][0][0],
            "chunk_paper_id": metadata["paper_id"],
            "best_chunk_section": metadata.get("section", ""),
            "best_chunk_text": results["documents"][0][0],
            "chunk_distance": float(results["distances"][0][0]),
        }

    def search(self, query, top_k=5):
        """Return ranked papers, metadata, and supporting passages."""
        if not query.strip():
            raise ValueError("Query cannot be empty.")

        if not isinstance(top_k, int) or not 1 <= top_k <= self.paper_candidates:
            raise ValueError(
                f"top_k must be an integer from 1 to {self.paper_candidates}."
            )

        query_vector = self.embedder.embed_query(query)

        paper_ranking = self._rank_papers(query_vector)
        chunk_ranking = self._rank_chunks(query_vector)

        ranking, scores = self._combine_rankings(
            paper_ranking, chunk_ranking
        )

        results = []

        for paper_id in ranking[:top_k]:
            paper = self.papers.loc[paper_id]
            evidence = self._get_evidence(paper_id, query_vector)

            results.append({
                "paper_id": str(paper["arxiv_id"]),
                "title": paper["title"],
                "abstract": paper["abstract_clean"],
                "score": float(scores[paper_id]),
                **evidence,
            })

        return results