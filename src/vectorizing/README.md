# vectorizing

`embedder.py` holds `TextEmbedder`, the one place text is turned into vectors. The index (`src/indexing`) uses it to embed chunks, and search uses it to embed queries, so both always use the same model.

There is no separate vectorizing step to run. Embedding happens inside `python -m src.indexing.cli`, which only embeds papers that are new or have a newer version and stores the vectors in LanceDB next to their text and metadata (see `src/indexing/README.md`). An earlier standalone pipeline wrote `data/vectorized/embeddings.npy`, but nothing read that file and it re-embedded every chunk on each run, so it was removed. Its checks now run in `update_index`: chunks over the model's token limit are reported, and embeddings with the wrong count or NaN/infinite values stop the run before the index is changed. `validate_chunks` moved to `src/chunking/pipeline.py`.

## TextEmbedder

| method | what it does |
|---|---|
| `embed_documents(texts)` | chunk texts → float32 vectors, normalized to length 1 (so cosine similarity equals dot product) |
| `embed_query(query)` | one query → one vector; for bge models the query gets the prefix `Represent this sentence for searching relevant passages: `, chunks don't |
| `count_truncated(texts)` | how many texts are longer than the model's `max_seq_length` (512 for bge-small); the model silently drops everything past that |

Default model: `BAAI/bge-small-en-v1.5` (384 dimensions). It must match the tokenizer chunking counts tokens with (`--tokenizer` in `src/chunking`). Changing the model changes what the stored vectors mean, so the index refuses to mix them and needs `python -m src.indexing.cli --rebuild`. To compare models, build one index per model with `--model <name> --index-dir data/index_<name>` and run the retrieval benchmark against each.

```python
from src.vectorizing.embedder import TextEmbedder

embedder = TextEmbedder()
vectors = embedder.embed_documents(["chunk one", "chunk two"])   # shape (2, 384)
query = embedder.embed_query("how are companies evaluating LLM agents?")
```

Tests: `python -m pytest tests/test_vectorizing.py`
