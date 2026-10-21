# Retrieval Improvement Experiment

## Why we tested this

The baseline returned at least one relevant paper for every query, but only **67.0% of results were relevant** and **31.6% were highly relevant**. Ambiguous queries performed weakest. Q03 returned only four distinct papers, and Q14 and Q15 missed their expected papers.

We checked the database and confirmed that the missing target papers were indexed, but none appeared among the top 100 matching chunks.

**Hypothesis:** a paper’s title and abstract may communicate its main contribution more clearly than individual chunks. Combining both searches could improve retrieval relevance without changing the embedding model or rebuilding the database.

## What the script does

`run_benchmark_combined.py` runs the same 25 benchmark queries using two methods:

| **Method** | **How it works** |
| --- | --- |
| **100-chunk search** | Searches 100 chunks, keeps each paper’s best match, and returns five distinct papers. |
| **Combined search** | Searches titles and abstracts, then combines that paper ranking with the chunk-search ranking. Returns five distinct papers. |

Combined search takes up to 30 paper candidates from each search.

## How the rankings are combined

Combined search uses **reciprocal rank fusion (RRF)**. Each paper receives points based on its position in each search:

- A paper near the top of a list receives more points.
- A paper appearing in both lists receives points from both.
- Papers are sorted by their total points.

The 100-chunk method helps distinguish the benefit of searching more chunks from adding title/abstract search.

## Run

From the repository root:

```bash
python -m evaluation.improvements.run_benchmark_combined
```

Requires the existing local Chroma database, cleaned corpus, benchmark queries, and baseline labels.

Outputs are saved in `evaluation/results/`:

- `retrieval_results_chunks_100.csv`
- `retrieval_results_combined.csv`

The script preserves the baseline and refuses to overwrite existing experiment results. It reuses labels for matching query–paper pairs. A paper selected through title/abstract search may have no matching chunk in the benchmark output.

## Labeling

Labels follow our existing evaluation framework for retrieval relevance:

- **2 — Highly relevant:** the paper’s main contribution addresses the query’s topic.
- **1 — Somewhat relevant:** the paper addresses a useful related angle.
- **0 — Not relevant.**

Existing labels were preserved. The 39 missing combined-search labels were **AI-assisted**, based only on this framework and the supplied titles, abstracts, and chunks. These labels need human review before treating the measured gains as confirmed.

This experiment evaluates retrieved papers. It does not evaluate generated summaries, citation correctness, or business usefulness.
