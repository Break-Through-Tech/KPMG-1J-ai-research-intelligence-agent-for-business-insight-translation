# LanceDB index over the chunks from src/chunking: one row per chunk with its vector,
# its text, and the metadata needed to cite it and filter on it
# data/chunks.parquet -> data/index/ (LanceDB table "chunks" + index_manifest.json)

import lancedb
import pyarrow as pa
from lancedb.index import FTS

from ..vectorizing.pipeline import validate_chunks
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
    if saved and not rebuild:
        check_compatible(saved, current)
    db = lancedb.connect(index_dir)
    table = db.create_table(TABLE_NAME, schema = make_schema(current["embedding_dim"]),
                            mode="overwrite" if rebuild else "create", exist_ok = not rebuild)
    if rebuild or not saved:
        save_manifest(index_dir, current)
    return table

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


def update_index(table, chunks, embedder, index_dir) -> int:
    """embeds only new or changed papers and swaps them into the index. returns rows added"""
    validate_chunks(chunks)
    todo = papers_to_index(table, chunks)
    if not todo:
        print("index is already up to date")
        return 0

    new = chunks[chunks["paper_id"].isin(todo)].reset_index(drop=True)
    print(f"embedding {len(new):,} chunks from {len(todo):,} new or updated papers")
    vectors = embedder.embed_documents(new["text_for_embedding"].astype(str).tolist())

    rows = new[METADATA_COLUMNS].copy()
    rows["vector"] = list(vectors)

    # drop any older version first. if a crash happens in between, those papers are just
    # missing from the index, so the next run sees them as new and adds them back
    table.delete(_in_list("paper_id", todo))
    table.add(pa.Table.from_pandas(rows, schema=table.schema, preserve_index=False))

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
    })
    return len(rows)

def search(table, embedder, query, k=10, where=None, hybrid=True) -> list[dict]:
    #top k chunks for a natural language query
    vector = embedder.embed_query(query)
    if hybrid:
        q = table.search(query_type="hybrid").vector(vector).text(query)
    else:
        q = table.search(vector)
    q = q.distance_type(METRIC)
    if where:
        q = q.where(where, prefilter=True)  # filter first, then rank, so we still get k results
    return q.limit(k).to_list()

    
