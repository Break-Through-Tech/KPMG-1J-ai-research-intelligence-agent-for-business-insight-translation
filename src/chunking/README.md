# chunking

## what I added (issue #12: chunking)

This step splits the cleaned paper text into chunks for the retriever, with metadata on every chunk so answers can cite the paper and section they came from. It builds on the two steps before it: Chythra's preprocessing cleans the text, and Abdullah's `prepare_for_chunking.py` decides what goes into chunking.

```
papers_clean.parquet ──► prepare_for_chunking.py ──► chunk_input.jsonl ──► src/chunking ──► data/chunks.parquet
   (Chythra)                 (Abdullah)              (one row per section)     (me)          (one row per chunk)
```

**new files**
- `src/chunking/chunker.py`: sentence splitting, fixed-size windows with overlap, and per-paper chunking
- `src/chunking/pipeline.py` and `cli.py`: run it on the whole corpus with one command
- `tests/test_chunking.py`: unit tests

## how to run

From the project root:

```bash
python prepare_for_chunking.py data/papers_clean.parquet data/chunk_input.jsonl
python -m src.chunking.cli
python -m pytest tests/
```

`papers_clean.parquet` can come from running `python -m src.preprocessing.cli` or from the published release (see `src/preprocessing/README.md`).

| argument | default | description |
|---|---|---|
| `--input` | `data/chunk_input.jsonl` | output of `prepare_for_chunking.py` |
| `--output` | `data/chunks.parquet` | one row per chunk |
| `--report` | `data/chunk_report.json` | chunk counts and sizes |
| `--chunk-tokens` | 512 | max chunk size |
| `--overlap-tokens` | 64 | overlap between neighbouring chunks |
| `--min-section-tokens` | 30 | shorter sections are merged into the next one |

## what's kept and what's removed

That's decided before chunking, in `prepare_for_chunking.py`, using the section labels from preprocessing. In short: the abstract and main sections are kept (with figure captions and tables), and references, appendix, title block, and acknowledgments are removed. The chunker uses whatever rows it gets.

## chunking strategy

Baseline: fixed-size chunks with overlap, with two rules on top.

1. **A chunk never crosses a section boundary.** Each section row is chunked on its own, so every chunk has exactly one section to cite. Sections under 30 tokens (often a heading with one sentence) are merged into the next section of the same paper.
2. **Chunks are built from whole sentences.** Sentences are added until the next one would go over 512 tokens. The overlap is the last ~64 tokens' worth of whole sentences from the previous chunk. A sentence only gets split if it alone is bigger than a chunk (usually a large table). Table rows and list items are kept as separate units.

Token counts use the same estimate as preprocessing (characters / 4). Once we pick an embedding model, we should switch to its tokenizer.

## output schema (`data/chunks.parquet`)

| column | description |
|---|---|
| `chunk_id` | `2609.30264v1::0003`, paper id + position in the paper |
| `paper_id`, `title`, `authors`, `arxiv_url` | paper metadata, from `chunk_input.jsonl` |
| `section`, `section_type`, `section_id` | `3.2 Threat Model`, `method`, and the section row it came from |
| `source` | `body`, `body_text` (paper had no headings), or `abstract_clean` |
| `chunk_index`, `n_chunks_in_paper` | position of the chunk in the paper |
| `text` | the chunk itself, for showing to users and the LLM |
| `text_for_embedding` | title + section + text, for the embedding step |
| `n_tokens` | estimated tokens in `text` |

## results on the current corpus

Published release with 1,200 papers (Sept 29 – Oct 2, 2026), 1,197 usable.

| metric | value |
|---|---|
| section rows in | 19,309 |
| chunks out | 32,374 (median 24 per paper, min 3, max 151) |
| tokens per chunk | median 414, max 512 |
| chunks under 50 tokens | 288 (0.9%) |
| duplicate chunk ids | 0 |
| largest section types | experiments 6,555, other 5,721, method 5,354, introduction 4,068 |

## open questions

- **Chunk size.** 512 tokens with 64 overlap is a common starting point. We should compare it with larger chunks (the preprocessing EDA assumed 800) on the benchmark questions.
- **Paper ids include the version.** `chunk_input.jsonl` uses `2609.30264v1`, so if a paper gets a v2, its chunks get new ids and the old ones should be removed from the index.
- **Math.** Some equations come through PDF extraction as scrambled text. That's an extraction issue, not a chunking one, but those chunks won't retrieve well.
