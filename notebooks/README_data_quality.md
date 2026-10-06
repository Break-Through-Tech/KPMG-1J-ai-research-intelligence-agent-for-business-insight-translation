# data quality EDA

## what I added (issue #8: data quality EDA)

Before we chunk, embed, or evaluate anything, we need to know the ingested data is actually correct. Chythra's `eda_corpus.ipynb` looks at what's in the text (length, headings, references). This notebook checks the data itself: types, missing values, fields that contradict each other, duplicates, and malformed values.

**new files**
- `notebooks/eda_data_quality.ipynb`: the data quality checks
- `reports/figures/dq_*.png`: missing values, PDF sizes, and field lengths

**edited files**
- `src/ingestion/fetch_metadata.py`: retries when arXiv returns HTTP 406 and falls back to the RSS feed (see below)
- `requirements.txt`: added `feedparser` for the RSS fallback

**how it follows through**

The checks answer a few questions the rest of the pipeline depends on:
- *Can we trust `ingestion_status`?* The pipeline skips any paper marked `complete` on rerun, so a `complete` paper with no text or a broken PDF would never get fixed. The notebook checks every one.
- *Is the same paper in here twice?* Ingestion dedupes on the versioned id, so v1 and v2 of a paper both get in. The notebook catches these, and preprocessing (`metadata.py`) keeps one per paper.
- *Is anything missing that `isna()` misses?* Blank strings and empty lists count as missing here.

---

## how to run

From the project root, with data already ingested:

```bash
python -m src.ingestion.cli --max-results 50
```

Then open `notebooks/eda_data_quality.ipynb`, set the kernel to `.venv`, and run all cells. If `data/papers_clean.parquet` exists, the notebook also checks the preprocessed output.

## what it checks

| problem | example | section that catches it |
|---|---|---|
| column holds the wrong type | dates stored as strings, list columns read back as numpy arrays | 1. schema |
| missing values `isna()` doesn't see | `""` title, whitespace-only abstract, empty author list | 2. missing values |
| status says one thing, data says another | `complete` with no text, PDF missing or not a real PDF, URL pointing to a different paper | 3. consistency |
| partial download that never gets retried | a PDF cut off mid-download, under 20 KB | 3. consistency |
| same paper stored twice | `2609.26780v1` and `2609.26780v2`, same title or identical text under different ids | 4. duplicates |
| malformed values | bad id format, `updated` before `published`, primary category missing from `categories` | 5. validity |
| messy author lists | the same name listed twice, an affiliation inside a name | 5. validity |
| preprocessing broke something | papers dropped, duplicate ids, empty `body_text` | 7. preprocessed output |

## outputs

| file | description |
|---|---|
| `data/data_quality_flags.csv` | one row per paper: `arxiv_id`, `n_flags`, and which checks it failed. Not committed |
| `reports/figures/dq_missing_values.png` | missing values by column, null vs. blank |
| `reports/figures/dq_pdf_sizes.png` | PDF size on disk, with the partial-download line at 20 KB |
| `reports/figures/dq_field_lengths.png` | title, abstract, author, and category counts per paper |

The last cell prints a findings table built from the results, so the numbers can't go stale.

## results on the current corpus

50 papers published 2026-09-25 between 13:04 and 17:59 UTC, run on 2026-09-28.

| check | result |
|---|---|
| ingestion status | 50/50 complete |
| schema | matches |
| missing values | none |
| contradictions | none |
| duplicates | none |
| invalid values | none |

This mainly shows the pipeline works end to end. All 50 papers came from about 5 hours of submissions, which is too short for some problems to show up. Version duplicates, for example, only appear after papers get revised. The corpus is now 201 papers, so these numbers should be updated from a rerun.

## arXiv HTTP 406 errors

In September 2026, the arXiv API started returning HTTP 406. From testing, it looks like rate limiting: requests worked at first, then all failed after about 20 in a few minutes, even simple ones.

`fetch_metadata.py` now retries 3 times with increasing waits, treats an empty response as a failure, and falls back to the RSS feed (`rss.arxiv.org`) if the API keeps failing. The RSS feed only covers the latest announcement day, has no real submission date, and doesn't label the primary category, so the API is still preferred. The output says which source was used.

## known limitations

- **Author checks are keyword-based.** They can miss affiliations and flag real names, so the notebook prints every flagged row to check by hand.
- **Near-duplicate titles use string similarity.** The same work under a very different title won't be caught. Embedding similarity would catch more once embeddings exist.
- **The 20 KB PDF threshold is a guess.** A real but very short PDF would be a false alarm.
