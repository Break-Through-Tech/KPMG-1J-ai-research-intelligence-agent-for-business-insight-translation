# indexing

This step turns the chunks into a searchable index. Each chunk gets an embedding vector, and LanceDB stores the vector together with the chunk's text and metadata, so a query returns text that can be cited and filtered by date or category. This is the retrieval half of the RAG pipeline; the agent calls `search()`.

```
papers_clean.parquet ──► prepare_for_chunking ──► chunk_input.jsonl ──► src/chunking ──► chunks.parquet ──► src/indexing ──► data/index/
                                                                                                          (embed + store)    chunks.lance/
                                                                                                                             index_manifest.json
```

**files**
- `store.py`: the table schema, `open_index`, `update_index` (embeds only new or changed papers) and `search`
- `manifest.py`: records the model and chunk settings the index was built with, and refuses to mix vectors built with different settings
- `cli.py`: build, update or search from the command line
- `tests/test_indexing.py`: unit tests (reopening, no re-embedding, version replacement, filters, hybrid search, settings check)

It reuses `TextEmbedder` and `validate_chunks` from `src/vectorizing`.

## how to run

From the project root:

```bash
python -m src.preprocessing.prepare_for_chunking     # data/papers_clean.parquet -> data/chunk_input.jsonl
python -m src.chunking.cli                           # -> data/chunks.parquet
python -m src.indexing.cli                           # -> data/index/ (only new or changed papers are embedded)
python -m src.indexing.cli --search "how are companies evaluating LLM agents?" --since 2026-09-01
```

To use the published index instead of building one, download it from the latest release:

```bash
gh release download --pattern index.tar.gz --dir data && tar -xzf data/index.tar.gz -C data
```

From Python:

```python
from src.vectorizing.embedder import TextEmbedder
from src.indexing.store import open_index, search

embedder = TextEmbedder()
table = open_index("data/index", embedder)
results = search(table, embedder, "retrieval augmented generation for audits", k=10,
                 where="published_date >= '2026-09-01' AND primary_category = 'cs.AI'")
```

| argument | default | description |
|---|---|---|
| `--chunks` | `data/chunks.parquet` | output of the chunking step |
| `--chunk-report` | `data/chunk_report.json` | the chunk settings are read from here and recorded in the manifest |
| `--index-dir` | `data/index` | where the LanceDB table and manifest live |
| `--model` | `BAAI/bge-small-en-v1.5` | embedding model |
| `--rebuild` | off | delete the index and embed everything again (needed after changing the model or chunk settings) |
| `--search` | | run a query instead of updating |
| `--k` | 5 | number of results for `--search` |
| `--since` | | only papers published on or after this date |

## how it works

- **one row per chunk:** `chunk_id`, `paper_id` (arXiv id without the version), `version`, `chunk_index`, `vector`, `text`, `title`, `authors`, `arxiv_url`, `section`, `section_type`, `published_date`, `primary_category`, `categories`. The stored `text` is the plain chunk; `text_for_embedding` (title + section + text) is only used to make the vector.
- **similarity:** cosine. The vectors are normalized, so this ranks the same as dot product.
- **no re-embedding:** `update_index` compares each paper's version in `chunks.parquet` with the index and only embeds papers that are new or have a newer version. A newer version's old rows are deleted first, so v1 and v2 never sit side by side.
- **hybrid search (default):** combines vector similarity with a full-text (keyword) index on `text`, which helps with exact names like model names and acronyms. Pass `hybrid=False` for vector-only search.
- **filters:** `where` is an SQL filter applied before ranking (`prefilter=True`), so you still get `k` results.
- **manifest:** `index_manifest.json` records the model, vector size, metric and chunk settings, plus the chunk and paper counts and date range. Opening the index with different settings raises an error instead of silently mixing incompatible vectors.
- **no approximate vector index yet:** under ~100k chunks LanceDB compares the query with every vector (exact and fast enough). Add an `IvfPq(distance_type="cosine")` index once the corpus is much larger.

## results on the current corpus

Built from the 2026-10-07 release (1,217 usable papers, Sept 29 to Oct 2, 2026), run on 2026-10-08.

| metric | value |
|---|---|
| chunks indexed | 32,880 from 1,217 papers |
| first build (embeds everything) | ~5.5 min on an M-series Mac; expect longer on the CPU-only GitHub runner |
| second run (nothing new) | 7 s, 0 chunks embedded |
| index size on disk / as `index.tar.gz` | 86 MB / 65 MB |
| chunks longer than the model's 512-token limit | 0 (was 5,221, 15.9%, before the chunker counted with bge's tokenizer; that build had 32,880 chunks, it's now 33,601) |

## in the GitHub workflow

`.github/workflows/update-corpus.yml` runs prepare, chunking and indexing after preprocessing, on top of the index from the previous release, and publishes `index.tar.gz` and `chunk_report.json` with each data release. If indexing fails, the data is still published along with the previous index, and the next run catches up.

## open questions

- **section labels for IEEE-style papers:** lettered subsections under Roman-numeral sections ("VI EXPERIMENTS" → "B Evaluation Metrics") aren't linked to their parent, so about 4.5% of chunks get the wrong `section_type` (mostly `other`). The text itself is correct main-body content; only the label used for citations is off. Fix belongs in `src/preprocessing/sections.py`.

- **storage:** the index travels as a release asset for now (2 GB per-file limit). The plan is to move it to a bucket (S3, GCS or R2), which LanceDB can query directly; `manifest.py` would then need `pyarrow.fs` instead of `Path`.
- **evaluation:** a known-item test (search each paper's title, check it comes back) and the benchmark queries, to compare chunk sizes, the bge query prefix and models.
