# Retriever comparison: Chroma vs LanceDB

Run on 2026-10-14 with `python -m evaluation.compare_retrievers --papers data/release/papers_clean.parquet`.
No LLM is involved, so this costs no Groq tokens.

## Setup

| Method | Index | How it ranks papers |
|---|---|---|
| `chroma-combined` | Chroma, built with the old chunker (88,467 chunks) | Thania's CombinedRetriever: title/abstract search + vector chunk search, merged with RRF |
| `lance` | LanceDB from `src/indexing`, new tokenizer-aware chunker (90,381 chunks) | Hybrid (vector + keyword) chunk search, grouped into papers |
| `lance-combined` | Same LanceDB index | Thania's method on LanceDB: title/abstract search + hybrid chunk search, merged with RRF |

- **Corpus:** the same 3,150 papers (`data-2026-10-14-0728` release, Sept 29 to Oct 11 2026) for all three.
- **Queries:** 31 in total.
  - The 25 in `evaluation/benchmark_queries.csv`.
  - Abdullah's 6 business questions from `src/benchmark_questions.csv`, labelled B01–B06. These are rewordings of Q10–Q15 with the same expected papers.
- **Embedding model:** all three use `BAAI/bge-small-en-v1.5`. Queries now get the bge search prefix (from `main`), so `chroma-combined` doesn't exactly match Thania's earlier numbers.

## Results

| Metric | chroma-combined | lance | lance-combined |
|---|---|---|---|
| Expected paper in top 5 (12 targeted queries) | 8/12 | 8/12 | 8/12 |
| Mean reciprocal rank of expected paper (MRR) | 0.542 | 0.431 | **0.667** |
| Title search test, 100 papers (hit@5 / MRR) | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| Precision on already-labelled results | 0.846 (39 labelled) | 0.806 (36) | **0.897** (39) |
| Strict precision on already-labelled results | 0.538 | 0.500 | **0.590** |
| Times the 3 recurring papers appear in the top 5 | 10 | **3** | 9 |
| Seconds per query (after startup) | 0.295 | **0.036** | **0.034** |
| Index size on disk | 1.8 GB | 236 MB | 236 MB |

Rank of the expected paper for each targeted query (0 = not in the top 5):

| Query | chroma-combined | lance | lance-combined |
|---|---|---|---|
| Q10 / B01 (simulated users) | 1 / 1 | 1 / 1 | 1 / 1 |
| Q11 / B02 (reasoning traces) | 4 / 4 | 4 / 4 | **1 / 1** |
| Q12 / B03 (agent plans) | 1 / 1 | 3 / 3 | 1 / 1 |
| Q13 / B04 (gender bias) | 1 / 1 | 1 / 1 | 1 / 1 |
| Q14 / B05 (model confidence) | 0 / 0 | 0 / 0 | 0 / 0 |
| Q15 / B06 (long-context memory) | 0 / 0 | 0 / 0 | 0 / 0 |

Top-5 overlap between methods (mean Jaccard): chroma-combined vs lance-combined 0.63, lance vs lance-combined 0.39, chroma-combined vs lance 0.28.

## What this shows

- **`lance-combined` is the best of the three.**
  - It finds the same expected papers as the others and ranks every one of them first.
  - It has the highest precision on the labelled results.
  - It is about 9× faster per query than Chroma, and its index is about 8× smaller.

  It is now the pipeline default (`--retriever lance-combined`).
- **Thania's ranking method matters more than the database.** Plain `lance` gets the lowest MRR. Adding the title/abstract ranking on top of it improves results the most.
- **Plain `lance` repeats the recurring papers least** (3 vs 9–10), but it is worse at putting the right paper first.
- **Q14 and Q15 look like gaps in the answer key, not retrieval failures.** The expected papers rank 8th (Q14) and 21st/22nd (Q15) in `lance-combined`. The papers ranked above them are on-topic: confidence calibration for Q14, KV-cache and memory compression for Q15. The expected papers were picked from a 1,220-paper corpus, and the corpus has since grown to 3,150.

## Caveats

- **Only about 25% of results have relevance labels.** Labels exist for 36–39 of the 155 results per method; the others are papers Thania never labelled. The precision numbers are only a hint until the blank `relevance_label` cells in `retriever_comparison_results.csv` are labelled (0/1/2) in Task #4.
- **The title search test is too easy.** All three get every title right, so it only confirms that each index is complete.
- **The chunkers differ.** Chroma uses the old chunker and LanceDB the new one, so this compares the whole setup, not only the database.
- **Results depend on wording.** "Can an AI model's step-by-step reasoning be trusted?" returns papers about trust in robots and human-AI trust from *every* retriever, including vector-only search. The longer benchmark wording (Q11) finds the right paper. This comes from the embedding model, not from LanceDB, and it is what query rewriting (`src/rag/query_rewriter.py`) or a stronger embedding model would address.
- **Reference lists are indexed.** Bibliography chunks sometimes rank highly (for example in `python -m src.indexing.cli --search "large language model agents"`). Filtering them out at chunking time is a likely easy improvement.

## Files

- `retriever_comparison_results.csv`: top 5 per method and query, with `is_expected` and `relevance_label` (blank = needs labelling).
- `retriever_comparison_summary.csv`: the metrics above.
- `retriever_comparison_overlap.csv`: top-5 overlap between methods.
- `retriever_comparison_known_items.csv`: title search test ranks.
- `thania_relevance_labels.csv`: Thania's 164 query–paper labels from `thania-pipeline-implementation`, reused here.
