# evaluation

How we test the Research Insight Agent: benchmark questions, scripts that compare different versions of the pipeline, and the saved results.

## Benchmark questions

| File | What it is |
|---|---|
| `benchmark_queries.csv` | 25 benchmark questions (`Q01`–`Q25`) with a category. The targeted ones (`Q10`–`Q15`) list the paper IDs we expect the search to find. |
| `../src/benchmark_questions.csv` | 6 business-style rewordings of `Q10`–`Q15` with the same expected papers and the evidence for each (labelled `B01`–`B06` in the retriever comparison). |
| `../src/evaluation/gold_standard_examples.md` | 5 human-written business briefs used as the standard the generated briefs should match. |

## Scripts

Run from the repo root, with the virtual environment active.

| Script | What it compares | Needs an API key? |
|---|---|---|
| `compare_retrievers.py` | Three search methods (`chroma-combined`, `lance`, `lance-combined`) on the benchmark: expected paper in the top 5, mean reciprocal rank, precision on labelled results, speed | No |
| `compare_context.py` | Paper text sent to the summary step with and without the compressor (`src/pipeline/compress.py`): estimated tokens and how many numbers and caveats survive | No (offline). With `--llm` it calls the model. |
| `../src/evaluation/run_retrieval_benchmark.py` | Search results for each business question as written vs. rewritten by the query rewriter | No |

```bash
python -m evaluation.compare_retrievers --papers data/papers_clean.parquet
python -m evaluation.compare_context
python -m evaluation.compare_context --llm --provider nvidia --questions Q10,Q11,Q12,Q13,Q14,Q15
```

The full pipeline benchmark (search, summary and brief for every question) is run with `python -m src.pipeline.cli --benchmark ...`; see `src/pipeline/README.md`.

## Results (`results/`)

| File | What it contains |
|---|---|
| `retriever_comparison.md` | **Start here for search.** Write-up of the three-retriever comparison and why `lance-combined` became the default. |
| `retriever_comparison_summary.csv` | One row per method with the summary metrics |
| `retriever_comparison_results.csv` | Every query's top 5 papers per method, with relevance labels where they exist |
| `retriever_comparison_known_items.csv` | Title search test: can each method find 100 papers by their own title? |
| `retriever_comparison_overlap.csv` | How much the top 5 results of each pair of methods overlap |
| `thania_relevance_labels.csv` | Relevance labels (0 = not relevant, 1 = partly, 2 = relevant) for retrieved papers |
| `end_to_end_outputs.jsonl`, `end_to_end_outputs_v2.jsonl` | Full pipeline answers (papers, summary, brief, citation check) for the benchmark questions |
| `end_to_end_outputs_lance_mixed.jsonl` | The same with the LanceDB retriever, answered with both Groq and Gemini |
| `task8_failure_cases.md` | **Start here for quality.** 5 real failure cases: what went wrong, the likely cause and a suggested fix |
| `context_compression_offline.csv` | Per question: paper-text tokens before and after compression, and how many numbers and caveats were kept |
| `context_compression_llm.csv` | 6 questions × 3 versions (full, compressed, compact): tokens sent, tokens written, time, citation and number checks |
| `context_compression_llm.jsonl` | The same test with the full summaries, to compare answers word for word |

## Main findings

- **Search:** `lance-combined` ranked every expected paper it found in first place (mean reciprocal rank 0.667 vs 0.542 and 0.431), had the highest precision on labelled results (0.897), and ran about 9× faster than the first version.
- **Answer key gaps:** the expected papers for `Q14` and `Q15` were picked from a smaller corpus; the papers now ranked above them are on-topic.
- **Token use:** compression cut the paper text by about 4–7% without accuracy problems, but the model wrote longer answers, so total tokens didn't go down and answers took longer. It is off by default.
- **Failure cases:** irrelevant papers retrieved, results that change with question wording, outdated benchmark expectations, and noisy reference-list chunks.

## Known gaps

- Only about 25% of retrieved results have relevance labels, so precision numbers are a hint until the blank `relevance_label` cells in `retriever_comparison_results.csv` are filled in.
- The LLM comparison of compression covers 6 questions with one model (NVIDIA Nemotron Ultra).
