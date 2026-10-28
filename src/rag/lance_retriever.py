# Paper-level retrievers on top of the LanceDB index from src/indexing
#
# LanceRetriever:          Grace's hybrid chunk search, grouped into papers
# LanceCombinedRetriever:  Thania's CombinedRetriever method (title/abstract search
#                          + chunk search, merged with RRF) on the LanceDB index
#
# Both return the same paper dicts as CombinedRetriever.search, so the
# pipeline (src/pipeline) works with either one unchanged. Each paper also
# carries "passages": its most relevant results passage and its limitations
# (or conclusion) passage, so the summary can report findings and caveats
# rather than only what the introduction says.

import re

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from src.indexing.store import load_paper_vectors, open_index, paper_text, search as index_search
from src.preprocessing.metadata import split_version
from src.vectorizing.embedder import TextEmbedder

# Extra passages sent for each paper: (label, section types to try in order).
# The first group with a chunk in the paper is used. "discussion" is left out
# because its most common heading is "Ethics Statement".
PASSAGES = [
    ("results", [("results", "experiments")]),
    ("limitations", [("limitations",), ("conclusion",)]),
]


# Filters the UI can send: {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "categories": ["cs.CL"]}
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CATEGORY_PATTERN = re.compile(r"^[A-Za-z-]+(\.[A-Za-z-]+)?$")


def clean_filters(filters):
    """
    Check the filters and return them in a fixed shape, or None when none are set.
    Raises ValueError on a bad date or category, since they go into a where clause.
    """
    if not filters:
        return None

    since = filters.get("since") or None
    until = filters.get("until") or None

    for date in (since, until):
        if date is not None and not (isinstance(date, str) and DATE_PATTERN.match(date)):
            raise ValueError(f"Dates must look like 2026-10-05, not {date!r}.")

    if since and until and since > until:
        raise ValueError("The start date is after the end date.")

    categories = list(filters.get("categories") or [])

    for category in categories:
        if not (isinstance(category, str) and CATEGORY_PATTERN.match(category)):
            raise ValueError(f"Unknown category {category!r}.")

    if not (since or until or categories):
        return None

    return {"since": since, "until": until, "categories": categories}


def filter_clause(filters):
    """LanceDB where clause for the chunk search, or None when there are no filters."""
    filters = clean_filters(filters)
    if not filters:
        return None

    parts = []
    # dates are stored as "YYYY-MM-DD" text, which compares correctly as text
    if filters["since"]:
        parts.append(f"published_date >= '{filters['since']}'")
    if filters["until"]:
        parts.append(f"published_date <= '{filters['until']}'")
    if filters["categories"]:
        parts.append(f"primary_category IN ({_quoted(filters['categories'])})")

    return " AND ".join(parts)


def base_id(paper_id):
    """Treat arXiv versions such as v1 and v2 as the same paper."""
    return re.sub(r"v\d+$", "", str(paper_id).strip())


def _quoted(values):
    """SQL string literals for a where clause, with quotes escaped"""
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


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
        passages=True,
    ):
        self.chunk_pool = 100
        self.hybrid = hybrid
        # False returns only the best chunk per paper, e.g. for retrieval-only benchmarks
        self.passages = passages

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

        # dates and categories are only needed for filters, and older files may not have them
        available = set(pq.read_schema(papers_path).names)
        columns = ["arxiv_id", "title", "abstract_clean"] + [
            c for c in ("published_date", "primary_category") if c in available
        ]

        papers = pd.read_parquet(papers_path, columns=columns)
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

        if "published_date" in papers:
            # same "YYYY-MM-DD" text as the index, whatever type the file stores
            papers["published_date"] = (
                pd.to_datetime(papers["published_date"], errors="coerce")
                .dt.strftime("%Y-%m-%d").fillna("")
            )

        return papers.set_index("base_id").sort_index()

    def _search_chunks(self, query, vector, k, where=None):
        return index_search(
            self.table, self.embedder, query, k=k, where=where,
            hybrid=self.hybrid, vector=vector
        )

    def _best_chunks(self, query, vector, where=None):
        """
        From one chunk search, in rank order:
        best:     each paper's best chunk, which ranks the papers
        evidence: each paper's best chunk that isn't its abstract, which is
                  what the LLM reads (it gets the abstract separately)
        """
        best = {}
        evidence = {}

        for row in self._search_chunks(query, vector, self.chunk_pool, where=where):
            best.setdefault(row["paper_id"], row)
            if row.get("section_type") != "abstract":
                evidence.setdefault(row["paper_id"], row)

        return best, evidence

    def _search_paper(self, paper_id, query, vector, types=None, exclude=None):
        """Best chunk within one paper, optionally only from some section types."""
        where = f"paper_id = {_quoted([paper_id])}"
        if types:
            where += f" AND section_type IN ({_quoted(types)})"
        if exclude:
            where += f" AND section_type NOT IN ({_quoted(exclude)})"

        rows = self._search_chunks(query, vector, 1, where=where)

        return rows[0] if rows else None

    def _main_evidence(self, paper_id, query, vector, evidence):
        """
        The paper's best non-abstract chunk: from the shared search if it was
        there, else searched within the paper. Papers with nothing but an
        abstract chunk fall back to it.
        """
        row = (
            evidence.get(paper_id)
            or self._search_paper(paper_id, query, vector, exclude=["abstract"])
            or self._search_paper(paper_id, query, vector)
        )

        if row is None:
            raise RuntimeError(f"No supporting chunk found for {paper_id}.")

        return row

    def _extra_passages(self, paper_id, query, vector, used_chunk_id):
        """The paper's most relevant results and limitations passages (see PASSAGES)."""
        passages = []
        used = {used_chunk_id}

        for label, type_groups in PASSAGES:
            row = None
            for types in type_groups:
                row = self._search_paper(paper_id, query, vector, types=types)
                if row:
                    break

            if row and row["chunk_id"] not in used:
                used.add(row["chunk_id"])
                passages.append({
                    "label": label,
                    "section": row.get("section") or "",
                    "section_type": row["section_type"],
                    "chunk_id": row["chunk_id"],
                    "text": row["text"],
                })

        return passages

    def _paper_result(self, paper_id, score, query, vector, evidence):
        paper = self.papers.loc[paper_id]
        row = self._main_evidence(paper_id, query, vector, evidence)

        return {
            "paper_id": str(paper["arxiv_id"]),
            "title": paper["title"],
            "abstract": paper["abstract_clean"],
            "score": float(score),
            **_evidence(row),
            "passages": (
                self._extra_passages(paper_id, query, vector, row["chunk_id"])
                if self.passages else []
            ),
        }

    def _check_top_k(self, query, top_k, limit):
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query cannot be empty.")

        if not isinstance(top_k, int) or not 1 <= top_k <= limit:
            raise ValueError(f"top_k must be an integer from 1 to {limit}.")

    def paper_mask(self, filters):
        """True for each paper (in self.papers order) that passes the filters."""
        filters = clean_filters(filters)
        mask = np.ones(len(self.papers), dtype=bool)

        if not filters:
            return mask

        dated = filters["since"] or filters["until"]
        if (dated and "published_date" not in self.papers) or (
            filters["categories"] and "primary_category" not in self.papers
        ):
            raise ValueError(
                "This papers file has no dates or categories, so it can't be filtered. "
                "Use a newer papers_clean.parquet."
            )

        if filters["since"]:
            mask &= (self.papers["published_date"] >= filters["since"]).to_numpy()
        if filters["until"]:
            mask &= (self.papers["published_date"] <= filters["until"]).to_numpy()
        if filters["categories"]:
            mask &= self.papers["primary_category"].isin(filters["categories"]).to_numpy()

        return mask

    def search(self, query, top_k=5, filters=None):
        """
        Return the top papers with their best supporting chunk.
        filters: optional {"since", "until", "categories"} (see clean_filters)
        """
        self._check_top_k(query, top_k, self.chunk_pool)
        where = filter_clause(filters)

        vector = self.embedder.embed_query(query)
        best, evidence = self._best_chunks(query, vector, where)

        results = []

        for paper_id, row in list(best.items())[:top_k]:
            score = row.get("_relevance_score", 1.0 - row.get("_distance", 0.0))
            results.append(self._paper_result(paper_id, score, query, vector, evidence))

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
        passages=True,
    ):
        super().__init__(papers_path, index_dir, hybrid, embedder, passages)

        # Same settings as CombinedRetriever and Thania's benchmark
        self.paper_candidates = 30
        self.rrf_constant = 60

        self.paper_ids = self.papers.index.tolist()
        self.paper_vectors = self._load_paper_vectors(index_dir)

    def _load_paper_vectors(self, index_dir):
        """
        Title/abstract vectors, read from the index (src/indexing stores them).
        Papers it has no vector for, or only one from another version, are
        embedded here, so an index built before paper vectors existed still works.
        """
        stored = load_paper_vectors(index_dir)
        versions = [split_version(str(arxiv_id))[1] for arxiv_id in self.papers["arxiv_id"]]

        vectors = np.zeros(
            (len(self.paper_ids), self.embedder.model.get_embedding_dimension()),
            dtype=np.float32,
        )
        missing = []

        for position, (paper_id, version) in enumerate(zip(self.paper_ids, versions)):
            saved = stored.get(paper_id)
            if saved and saved[0] == version:
                vectors[position] = saved[1]
            else:
                missing.append(position)

        if missing:
            print(f"Embedding {len(missing):,} paper titles and abstracts the index "
                  "doesn't store (run python -m src.indexing.cli to add them)")
            texts = [
                paper_text(self.papers["title"].iloc[p], self.papers["abstract_clean"].iloc[p])
                for p in missing
            ]
            vectors[missing] = self.embedder.embed_documents(texts)

        return vectors

    def _rank_papers(self, query_vector, mask=None):
        """Rank papers by title/abstract cosine similarity, only those in mask if given."""
        similarities = self.paper_vectors @ query_vector

        positions = np.argsort(-similarities, kind="stable")
        if mask is not None:
            positions = positions[mask[positions]]
        positions = positions[:self.paper_candidates]

        return [self.paper_ids[position] for position in positions]

    def search(self, query, top_k=5, filters=None):
        """
        Return ranked papers, metadata, and supporting passages.
        filters: optional {"since", "until", "categories"} (see clean_filters)
        """
        self._check_top_k(query, top_k, self.paper_candidates)
        where = filter_clause(filters)
        mask = self.paper_mask(filters) if where else None

        vector = self.embedder.embed_query(query)

        best, evidence = self._best_chunks(query, vector, where)

        paper_ranking = self._rank_papers(vector, mask)
        chunk_ranking = list(best)[:self.paper_candidates]

        ranking, scores = rrf_merge(
            [paper_ranking, chunk_ranking], k=self.rrf_constant
        )

        return [
            self._paper_result(paper_id, scores[paper_id], query, vector, evidence)
            for paper_id in ranking[:top_k]
        ]
