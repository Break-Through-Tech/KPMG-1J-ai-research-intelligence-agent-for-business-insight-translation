# Baseline Retrieval Evaluation

## Summary

We ran **25 benchmark queries** through the baseline retrieval pipeline and labeled the top 5 papers for each query (**124 papers** total). **All 25 queries** returned at least one relevant paper, and **67%** of returned papers were relevant (labeled 1 or 2). Only **32%** were highly relevant (labeled 2). **Ambiguous queries** were the weakest, with only **14%** of returned papers highly relevant. For the specific queries, **4 of 6** expected papers were found.

## Setup

- **Corpus:** 1,220 cs.AI papers from the published `papers_clean` release, split into 32,880 chunks.
- **Retriever:** `BAAI/bge-small-en-v1.5` embeddings in ChromaDB, cosine distance, no reranking.
- **Queries:** 25 in `benchmark_queries.csv`: 6 general, 6 business, 7 ambiguous, and 6 specific (each tied to a known paper).
- **How papers were selected:** The retriever returns chunks, so we searched the top 30 chunks per query, kept each paper's best chunk, and took the top 5 papers. (Q03 had only 4 distinct papers in its top 30 chunks, so 124 rows total.)
- **Labeling:** Labeling was based on our evaluation framework (relevance of retrieved papers), using each paper's title, abstract, and best-matching chunk:
  - **2** = highly relevant
  - **1** = somewhat relevant
  - **0** = not relevant

  Because every paper in the corpus is narrow, a 2 means the paper's main contribution is on the query's topic, even if it covers only one technique. A 1 means a related angle (for example, an efficiency paper for an accuracy query).

Files: `evaluation/results/retrieval_results_baseline.csv` (labels) and `evaluation/results/retrieval_scores_baseline.csv` (per-query scores).

## Results

| Category | Queries | Precision | Strict precision | Hit |
|---|---|---|---|---|
| General | 6 | 0.76 | 0.48 | 1.00 |
| Business | 6 | 0.73 | 0.47 | 1.00 |
| Ambiguous | 7 | 0.63 | 0.14 | 1.00 |
| Specific | 6 | 0.57 | 0.20 | 1.00 |
| **Overall** | **25** | **0.67** | **0.32** | **1.00** |

- **Precision:** share of the 5 papers labeled 1 or 2.
- **Strict precision:** share labeled 2 only.
- **Hit:** whether at least one relevant paper appeared in the top 5.

**Specific queries, expected paper found in the top 5:**

| Query | Found |
|---|---|
| Q10 simulated users | Yes (rank 1) |
| Q11 chain-of-thought traces | Yes (rank 3) |
| Q12 plan execution | Yes (rank 1) |
| Q13 gender bias | Yes (retrieved as v2, expected v1) |
| Q14 model confidence | No |
| Q15 long-context cost | No (neither of the 2 expected papers) |

Precision is lower for the specific queries because a narrow question only has one or two truly relevant papers, so the rest of the top 5 will be filler. Target-paper recall is the better measure for that group.

## Where retrieval worked and where it struggled

**Worked well:** Broad topics with many matching papers. For Q01, Q05, Q11, Q16, Q17, Q21, and Q24, every returned paper was at least somewhat relevant.

**Struggled:**
- **Q02 (efficiency) and Q08 (incorrect information):** Only 1 of 5 papers was relevant. Results matched on words like "LLM" or "agent" instead of the topic.
- **Q14 and Q15:** The expected papers were not retrieved, though the Q14 results were still on topic.
- **Ambiguous queries:** Vague wording returned related papers but rarely a direct answer.
- **Repeated papers:** One paper on user feedback for generative AI appeared in 6 of the 25 queries.

## Note

`src/rag/indexer.py` needed a small fix to index the data locally (array-valued author metadata caused a crash).
