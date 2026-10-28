# LanceDB index over the chunks from src/chunking: one row per chunk with its vector,
# its text, and the metadata needed to cite it and filter on it
# data/chunks.parquet -> data/index/ (LanceDB table "chunks" + index_manifest.json)

import time
from pathlib import Path

import lancedb
import numpy as np
import pyarrow as pa
from lancedb.index import FTS

from ..chunking.pipeline import validate_chunks
from .manifest import check_compatible, load_manifest, save_manifest

TABLE_NAME = "chunks"
METRIC = "cosine"  # vectors are normalized, so this ranks the same as dot product


def make_schema(dim: int) -> pa.Schema:
    return pa.schema([
        pa.field("chunk_id", pa.string()),
        pa.field("paper_id", pa.string()),
        pa.field("version", pa.int32()),
        pa.field("chunk_index", pa.int32()),
        pa.field("vector", pa.list_(pa.float32(), dim)),  # fixed size, so LanceDB knows it's the vector column
        pa.field("text", pa.string()),                    # the chunk itself, what the LLM reads
        pa.field("title", pa.string()),
        pa.field("authors", pa.list_(pa.string())),
        pa.field("arxiv_url", pa.string()),
        pa.field("section", pa.string()),
        pa.field("section_type", pa.string()),
        pa.field("published_date", pa.string()),          # "YYYY-MM-DD" sorts and compares correctly as text
        pa.field("primary_category", pa.string()),
        pa.field("categories", pa.list_(pa.string())),
    ])


# every column except the vector comes straight from chunks.parquet
METADATA_COLUMNS = [f.name for f in make_schema(1) if f.name != "vector"]


def open_index(index_dir, embedder, chunk_config = None, rebuild = False):
    #opens the table and checks that it was built with the same settings
    current = {
        "model_name": embedder.model_name, 
        "embedding_dim": embedder.model.get_embedding_dimension(),
        "metric": METRIC,
        "chunk_config": chunk_config
    }
    saved = load_manifest(index_dir)
    if chunk_config is None and saved:
        # only searching (no chunk settings passed), so use the ones the index was built with
        current["chunk_config"] = saved.get("chunk_config")
    db = lancedb.connect(index_dir)
    schema = make_schema(current["embedding_dim"])
    table = db.create_table(TABLE_NAME, schema = schema,
                            mode="overwrite" if rebuild else "create", exist_ok = not rebuild)
    if not rebuild and table.count_rows() == 0:
        # an empty index has no vectors to mix up (e.g. a failed first run left it behind),
        # so start it fresh with the current settings instead of refusing
        table = db.create_table(TABLE_NAME, schema = schema, mode="overwrite")
        rebuild = True
    elif saved and not rebuild:
        check_compatible(saved, current)
    if rebuild or not saved:
        save_manifest(index_dir, current)
    return table

def indexed_versions(index_dir) -> dict[str, int]:
    """{paper_id: version} for every paper already in the index, {} if there is no index yet.
    reads only the two id columns and doesn't load the embedding model, so the chunking
    step can use it to skip papers that are already indexed"""
    if not Path(index_dir).exists():
        return {}
    db = lancedb.connect(index_dir)
    if TABLE_NAME not in db.list_tables().tables:
        return {}
    ids = db.open_table(TABLE_NAME).search().select(["paper_id", "version"]).limit(None).to_pandas()
    return {paper_id: int(version) for paper_id, version in ids.groupby("paper_id")["version"].max().items()}


def papers_to_index(table, chunks) -> set[str]:
    #paper ids that are new or whose chunks are a newer version than the index is
    latest = chunks.groupby("paper_id")["version"].max()
    if table.count_rows() == 0:
        return set(latest.index)
    #only the two id columns are read, never the vectors
    indexed = (table.search().select(["paper_id", "version"]).limit(None).to_pandas().groupby("paper_id")["version"].max())
    have = indexed.reindex(latest.index)
    return set(latest.index[have.isna() | (latest>have)])

def _in_list(column, values) -> str:
    quoted = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


def _add_papers(table, chunks, papers, embedder) -> int:
    """embeds one batch of papers and swaps them into the index. returns rows added"""
    new = chunks[chunks["paper_id"].isin(papers)].reset_index(drop=True)
    texts = new["text_for_embedding"].astype(str).tolist()
    # the model silently drops tokens past max_seq_length; chunking with --tokenizer should keep this at 0
    n_truncated = embedder.count_truncated(texts)
    if n_truncated:
        print(f"warning: {n_truncated:,} chunks are longer than {embedder.model.max_seq_length} tokens "
              f"and will be cut off when embedded")
    vectors = embedder.embed_documents(texts)
    # checked before anything is deleted, so a bad batch never replaces good rows
    if len(vectors) != len(new):
        raise RuntimeError(f"got {len(vectors)} embeddings for {len(new)} chunks")
    if not np.isfinite(vectors).all():
        raise RuntimeError("embeddings contain NaN or infinite values")

    rows = new[METADATA_COLUMNS].copy()
    rows["vector"] = list(vectors)

    # drop any older version first. if a crash happens in between, those papers are just
    # missing from the index, so the next run sees them as new and adds them back
    table.delete(_in_list("paper_id", papers))
    table.add(pa.Table.from_pandas(rows, schema=table.schema, preserve_index=False))
    return len(rows)


def update_index(table, chunks, embedder, index_dir, max_seconds=None,
                 papers_per_batch=200, clock=time.monotonic) -> int:
    """embeds only new or changed papers and swaps them into the index. returns rows added

    papers are added in batches, newest first, and each batch is saved as soon as it's embedded.
    with max_seconds, it stops after the batch that runs past the limit; the papers left over
    are counted in the manifest as backlog_papers and picked up by the next run
    """
    # no chunks happens when chunking skipped every paper because the index already has it
    if len(chunks) == 0:
        todo = set()
    else:
        validate_chunks(chunks)
        todo = papers_to_index(table, chunks)
    if not todo:
        print("index is already up to date")
        manifest = load_manifest(index_dir) or {}
        if manifest.get("backlog_papers"):
            save_manifest(index_dir, {**manifest, "backlog_papers": 0})
        return 0

    # newest papers first, so a run that stops early still makes the latest research searchable
    newest = chunks[chunks["paper_id"].isin(todo)].groupby("paper_id")["published_date"].max()
    order = newest.sort_values(ascending=False, kind="stable").index.tolist()
    n_chunks = int(chunks["paper_id"].isin(todo).sum())
    print(f"embedding {n_chunks:,} chunks from {len(order):,} new or updated papers")

    start = clock()
    added = 0
    done = 0
    while done < len(order):
        batch = order[done:done + papers_per_batch]
        added += _add_papers(table, chunks, batch, embedder)
        done += len(batch)
        print(f"indexed {done:,}/{len(order):,} papers ({added:,} chunks)")
        if max_seconds is not None and clock() - start >= max_seconds and done < len(order):
            print(f"stopped at the time limit, {len(order) - done:,} papers left for the next run")
            break

    # keyword index for hybrid search; after the first build, optimize() folds new rows in
    # (and compacts the small files each add creates)
    if not any(i.index_type == "FTS" for i in table.list_indices()):
        table.create_index("text", config=FTS())
    else:
        table.optimize()

    manifest = load_manifest(index_dir) or {}
    stats = table.search().select(["paper_id", "published_date"]).limit(None).to_pandas()
    save_manifest(index_dir, {
        **manifest,
        "n_chunks": int(table.count_rows()),
        "n_papers": int(stats["paper_id"].nunique()),
        "date_range": [stats["published_date"].min(), stats["published_date"].max()],
        "backlog_papers": len(order) - done,
    })
    return added

def search(table, embedder, query, k=10, where=None, hybrid=True, vector=None) -> list[dict]:
    #top k chunks for a natural language query
    #pass vector when the query is already embedded, so several searches for one question embed it once
    if vector is None:
        vector = embedder.embed_query(query)
    if hybrid:
        q = table.search(query_type="hybrid").vector(vector).text(query)
    else:
        q = table.search(vector)
    q = q.distance_type(METRIC)
    if where:
        q = q.where(where, prefilter=True)  # filter first, then rank, so we still get k results
    return q.limit(k).to_list()


# ---------- paper vectors ----------
# one vector per paper for its title + abstract, which LanceCombinedRetriever ranks papers by.
# stored next to the chunks so the retriever loads them instead of embedding every paper at startup

PAPERS_TABLE = "papers"


def paper_text(title, abstract) -> str:
    #the exact text the retriever compares a question against, so stored and fresh vectors match
    return f"{title}\n{abstract}"


def make_paper_schema(dim: int) -> pa.Schema:
    return pa.schema([
        pa.field("paper_id", pa.string()),   # base id, no version
        pa.field("version", pa.int32()),     # version of the papers_clean row that was embedded
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ])


def open_paper_table(index_dir, dim, rebuild=False):
    db = lancedb.connect(index_dir)
    return db.create_table(PAPERS_TABLE, schema=make_paper_schema(dim),
                           mode="overwrite" if rebuild else "create", exist_ok=not rebuild)


def load_paper_vectors(index_dir) -> dict:
    #{base paper id: (version, vector)}, empty if the index has no paper table yet (built before it existed)
    db = lancedb.connect(index_dir)
    if PAPERS_TABLE not in db.list_tables().tables:
        return {}
    rows = db.open_table(PAPERS_TABLE).to_arrow().to_pydict()
    return {
        paper_id: (version, np.asarray(vector, dtype=np.float32))
        for paper_id, version, vector in zip(rows["paper_id"], rows["version"], rows["vector"])
    }


def update_paper_vectors(index_dir, chunk_table, papers, embedder, batch_size=1000) -> int:
    """embeds title + abstract for every paper in the chunk index that has no paper vector yet,
    or one made from an older version. returns how many were embedded

    papers: papers_clean rows with base_id, version, title and abstract_clean.
    papers still waiting in the chunk backlog are skipped, they get a vector once they're indexed
    """
    indexed = set(chunk_table.search().select(["paper_id"]).limit(None).to_pandas()["paper_id"])
    papers = (papers[papers["base_id"].isin(indexed)]
              .sort_values("version").drop_duplicates("base_id", keep="last"))

    table = open_paper_table(index_dir, embedder.model.get_embedding_dimension())
    have = {paper_id: version for paper_id, (version, _) in load_paper_vectors(index_dir).items()}
    todo = papers[[have.get(p) != v for p, v in zip(papers["base_id"], papers["version"])]]
    if todo.empty:
        return 0

    print(f"embedding titles and abstracts of {len(todo):,} papers")
    for start in range(0, len(todo), batch_size):
        batch = todo.iloc[start:start + batch_size]
        texts = [paper_text(t, a) for t, a in
                 zip(batch["title"].fillna("").astype(str), batch["abstract_clean"].fillna("").astype(str))]
        vectors = embedder.embed_documents(texts)
        if not np.isfinite(vectors).all():
            raise RuntimeError("embeddings contain NaN or infinite values")
        rows = pa.table({
            "paper_id": batch["base_id"].astype(str).tolist(),
            "version": batch["version"].astype("int32").tolist(),
            "vector": list(vectors),
        }, schema=table.schema)
        table.delete(_in_list("paper_id", batch["base_id"]))
        table.add(rows)
    return len(todo)

