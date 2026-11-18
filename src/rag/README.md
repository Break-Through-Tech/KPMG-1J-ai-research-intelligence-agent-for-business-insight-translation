# RAG module (`src/rag/`)

Paper-level retrieval on top of the LanceDB index built by `src/indexing`. The pipeline (`src/pipeline`) and the web app (`src/app`) both search through these retrievers.

## Retrievers (`lance_retriever.py`)

| Class | How it ranks papers |
|---|---|
| `LanceCombinedRetriever` (default) | Thania's method: rank papers by title/abstract similarity and by their best chunk (hybrid vector + keyword search), then merge the two rankings with reciprocal rank fusion (k = 60). |
| `LanceRetriever` | Grace's hybrid chunk search only, grouped into papers by their best chunk. |

Both return the same list of paper dicts, so either can be passed to `answer_query`:

| Field | Meaning |
|---|---|
| `paper_id`, `title`, `abstract`, `score` | the paper and its rank score |
| `chunk_id`, `chunk_paper_id`, `best_chunk_section`, `best_chunk_text` | the paper's best non-abstract chunk, which the summary step reads |
| `chunk_distance` / `chunk_relevance` | vector distance (vector-only search) or relevance score (hybrid search) |
| `passages` | the paper's most relevant results passage and its limitations (or conclusion) passage, so the summary can report findings and caveats. `passages=False` skips them, e.g. for retrieval-only benchmarks. |

`search(query, top_k=5, filters=None)` also accepts filters from the ask page: `{"since": "YYYY-MM-DD", "until": "YYYY-MM-DD", "categories": ["cs.CL"]}`. They are checked by `clean_filters` before going into a LanceDB where clause.

On startup the retriever refuses to run if the index has papers that `papers_clean.parquet` doesn't, since that means the two came from different releases. `LanceCombinedRetriever` reads each paper's stored title/abstract vector from the index, and embeds any that are missing (run `python -m src.indexing.cli` to store them).

```python
from src.rag.lance_retriever import LanceCombinedRetriever

retriever = LanceCombinedRetriever()  # data/papers_clean.parquet and data/index
papers = retriever.search("How can companies check AI models for bias?", top_k=5)
```

How the two compare with each other and with the first Chroma version: `evaluation/results/retriever_comparison.md`.

## Query rewriting (`query_rewriter.py`)

`rewrite_query(question)` turns business-style wording into research-style search terms (for example "simulated users" becomes "user simulators") and drops filler words. The app searches with the question as typed; `python -m src.evaluation.run_retrieval_benchmark` compares search results with and without the rewriter.

## History

The first retriever (Thania's `CombinedRetriever`) used a local Chroma database. It was replaced by the LanceDB versions above, which ranked better and ran about 9× faster. The Chroma code has been removed; its benchmark numbers are kept in `evaluation/results/`.

Tests: `python -m pytest tests/test_lance_retriever.py`
