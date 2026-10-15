# Paper-level retrievers on top of the LanceDB index from src/indexing
#
# LanceRetriever:          Grace's hybrid chunk search, grouped into papers
# LanceCombinedRetriever:  Thania's CombinedRetriever method (title/abstract search
#                          + chunk search, merged with RRF) on the LanceDB index
#
# Both return the same paper dicts as CombinedRetriever.search, so the
# pipeline (src/pipeline) works with either one unchanged.

import re

import numpy as np
import pandas as pd

from src.indexing.store import open_index, search as index_search
from src.vectorizing.embedder import TextEmbedder


def base_id(paper_id):
    """Treat arXiv versions such as v1 and v2 as the same paper."""
    return re.sub(r"v\d+$", "", str(paper_id).strip())


def rrf_merge(rankings, k=60):
    """
    Reciprocal rank fusion: each paper gets 1 / (k + rank) points from every
    ranking it appears in. Same formula and tie-break as
    CombinedRetriever._combine_rankings.
    """
    scores = {}

    for ranking in rankings:
        for rank, paper_id in enumerate(ranking, start=1):
            scores[paper_id] = scores.get(paper_id, 0.0) + 1.0 / (k + rank)

    ranking = sorted(scores, key=lambda paper_id: (-scores[paper_id], paper_id))

    return ranking, scores


def _evidence(row):
    """Turn one LanceDB chunk row into the evidence fields the pipeline uses."""
    return {
        "chunk_id": row["chunk_id"],
        "chunk_paper_id": f"{row['paper_id']}v{row['version']}",
        "best_chunk_section": row.get("section") or "",
        "best_chunk_text": row["text"],
        # hybrid search returns a relevance score (higher is better),
        # vector-only search returns a distance (lower is better)
        "chunk_distance": (
            float(row["_distance"]) if "_distance" in row else None
        ),
        "chunk_relevance": (
            float(row["_relevance_score"]) if "_relevance_score" in row else None
        ),
    }


class LanceRetriever:
    """
    Search chunks with LanceDB hybrid (vector + keyword) search and return
    the top papers, each with its best matching chunk.
    """

    def __init__(
        self,
        papers_path="data/papers_clean.parquet",
        index_dir="data/index",
        hybrid=True,
        embedder=None,
    ):
        self.chunk_pool = 100
        self.hybrid = hybrid

        self.embedder = embedder or TextEmbedder()
        self.table = open_index(index_dir, self.embedder)

        if self.table.count_rows() == 0:
            raise ValueError(
                f"The index in {index_dir} is empty. Build it with: "
                "python -m src.indexing.cli"
            )

        self.papers = self._load_papers(papers_path)

    def _load_papers(self, papers_path):
        """
        Titles and abstracts for the indexed papers, keyed by base paper ID.
        Refuses to start if the index has papers the corpus file doesn't,
        which means they were built from different releases.
        """
        indexed = set(
            self.table.search()
            .select(["paper_id"])
            .limit(None)
            .to_pandas()["paper_id"]
        )

        papers = pd.read_parquet(
            papers_path, columns=["arxiv_id", "title", "abstract_clean"]
        )
        papers["base_id"] = papers["arxiv_id"].map(base_id)

        missing = indexed - set(papers["base_id"])

        if missing:
            raise ValueError(
                f"{len(missing)} indexed papers are missing from {papers_path}. "
                "Use the papers_clean.parquet the index was built from."
            )

        papers = papers[papers["base_id"].isin(indexed)].copy()
        # keep the newest version if a release lists a paper twice
        papers = papers.sort_values("arxiv_id").drop_duplicates("base_id", keep="last")

        papers["title"] = papers["title"].fillna("").astype(str)
        papers["abstract_clean"] = papers["abstract_clean"].fillna("").astype(str)

        return papers.set_index("base_id").sort_index()

    def _search_chunks(self, query, k, where=None):
        return index_search(
            self.table, self.embedder, query, k=k, where=where, hybrid=self.hybrid
        )

    def _best_chunks(self, query):
        """
        Papers in rank order with their best chunk, from one chunk search.
        Results come back best first, so a paper's first chunk is its best.
        """
        best = {}

        for row in self._search_chunks(query, self.chunk_pool):
            best.setdefault(row["paper_id"], row)

        return best

    def _paper_result(self, paper_id, score, chunk_row):
        paper = self.papers.loc[paper_id]

        return {
            "paper_id": str(paper["arxiv_id"]),
            "title": paper["title"],
            "abstract": paper["abstract_clean"],
            "score": float(score),
            **_evidence(chunk_row),
        }

    def _check_top_k(self, query, top_k, limit):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        if not isinstance(top_k, int) or not 1 <= top_k <= limit:
            raise ValueError(f"top_k must be an integer from 1 to {limit}.")

    def search(self, query, top_k=5):
        """Return the top papers with their best supporting chunk."""
        self._check_top_k(query, top_k, self.chunk_pool)

        best = self._best_chunks(query)

        results = []

        for paper_id, row in list(best.items())[:top_k]:
            score = row.get("_relevance_score", 1.0 - row.get("_distance", 0.0))
            results.append(self._paper_result(paper_id, score, row))

        return results


class LanceCombinedRetriever(LanceRetriever):
    """
    Thania's CombinedRetriever method on the LanceDB index:
    1. Rank papers by title/abstract similarity.
    2. Rank papers by their best chunk (hybrid search).
    3. Merge both rankings with reciprocal rank fusion.
    4. Return each selected paper with its best matching chunk.
    """

    def __init__(
        self,
        papers_path="data/papers_clean.parquet",
        index_dir="data/index",
        hybrid=True,
        embedder=None,
    ):
        super().__init__(papers_path, index_dir, hybrid, embedder)

        # Same settings as CombinedRetriever and Thania's benchmark
        self.paper_candidates = 30
        self.rrf_constant = 60

        self.paper_ids = self.papers.index.tolist()

        texts = (self.papers["title"] + "\n" + self.papers["abstract_clean"]).tolist()

        # Embedded once at startup, then reused for every query
        self.paper_vectors = self.embedder.embed_documents(texts)

    def _rank_papers(self, query_vector):
        """Rank papers by title/abstract cosine similarity."""
        similarities = self.paper_vectors @ query_vector

        positions = np.argsort(-similarities, kind="stable")[:self.paper_candidates]

        return [self.paper_ids[position] for position in positions]

    def _evidence_for(self, paper_id, query):
        """Best chunk within one paper, for papers found only by title/abstract."""
        escaped = str(paper_id).replace("'", "''")
        rows = self._search_chunks(query, 1, where=f"paper_id = '{escaped}'")

        if not rows:
            raise RuntimeError(f"No supporting chunk found for {paper_id}.")

        return rows[0]

    def search(self, query, top_k=5):
        """Return ranked papers, metadata, and supporting passages."""
        self._check_top_k(query, top_k, self.paper_candidates)

        query_vector = self.embedder.embed_query(query)

        best = self._best_chunks(query)

        paper_ranking = self._rank_papers(query_vector)
        chunk_ranking = list(best)[:self.paper_candidates]

        ranking, scores = rrf_merge(
            [paper_ranking, chunk_ranking], k=self.rrf_constant
        )

        results = []

        for paper_id in ranking[:top_k]:
            row = best.get(paper_id) or self._evidence_for(paper_id, query)
            results.append(self._paper_result(paper_id, scores[paper_id], row))

        return results
