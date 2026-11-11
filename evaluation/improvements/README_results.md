# Retrieval Results Comparison

## How results were scored

`compare_retrieval_methods.py` uses the scoring logic from the previous evaluation on `thania-evaluation`, adjusted to compare three methods and save comparison tables. The original baseline script and baseline score file remain unchanged.

Run after completing the labels:

```bash
python -m evaluation.improvements.compare_retrieval_methods
```

| **Metric** | **Meaning** |
| --- | --- |
| **Precision** | Share of returned papers labeled 1 or 2. |
| **Strict precision** | Share labeled 2. |
| **Hit** | Whether a query returned at least one relevant paper. |
| **Target recall (`target_found`)** | Fraction of a specific query’s expected papers retrieved, ignoring arXiv version endings. |

Scores are calculated per query, then averaged. Target recall averages only the six specific queries. Q15 has two expected papers, so finding one would score 0.5.

Precision uses the number of papers actually returned: four for baseline Q03 and five otherwise.

## Overall results

| **Method** | **Precision** | **Strict precision** | **Hit** | **Target recall** |
| --- | ---: | ---: | ---: | ---: |
| Baseline: 30 chunks | 67.0% | 31.6% | 100% | 66.7% |
| 100 chunks | 67.2% | 32.0% | 100% | 66.7% |
| Combined search | **81.6%** | **40.8%** | 100% | 66.7% |

Increasing the chunk pool added a fifth paper for Q03 but made little difference overall.

Combined search improved precision by **14.6 percentage points** and strict precision by **9.2 points** over baseline.

## Results by category

Each cell shows **precision (1 or 2) / strict precision (2)**.

| **Category** | **Baseline** | **100 chunks** | **Combined** |
| --- | --- | --- | --- |
| General | 75.8% / 48.3% | 76.7% / 50.0% | 86.7% / 50.0% |
| Business | 73.3% / 46.7% | 73.3% / 46.7% | 90.0% / 60.0% |
| Ambiguous | 62.9% / 14.3% | 62.9% / 14.3% | 77.1% / 25.7% |
| Specific | 56.7% / 20.0% | 56.7% / 20.0% | 73.3% / 30.0% |

Business queries performed strongest, supporting the project’s business focus. Ambiguous queries improved but still returned relatively few highly relevant papers.

All methods found the expected papers for Q10–Q13. **Q14 and both Q15 targets remained missing from the top five.**
