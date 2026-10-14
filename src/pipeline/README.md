# End-to-End Pipeline (Task #3: Connect Retrieval + Summarization)

Takes a question in plain English and returns a cited summary of the relevant research.

```
question
  -> CombinedRetriever (src/rag/combined_retriever.py)    top 5 papers + best supporting chunk each
  -> format_retrieved_content                             paper ID, title, abstract, section, chunk text
  -> build_summarization_prompt (src/summarization)       Lakshmee's two-shot prompt
  -> GroqLLM (openai/gpt-oss-120b)                        4-section summary with [paper_id] citations
  -> check_citations                                      flags cited papers that were never retrieved
```

## Files

| File | Purpose |
|---|---|
| `pipeline.py` | `answer_query()`, `run_benchmark()`, formatting and citation check |
| `llm.py` | `GroqLLM`, same model and settings as the summarization testing |
| `cli.py` | command line entry point |

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Build the Chroma database (one time, about 20–40 minutes on a laptop CPU):

```bash
mkdir -p data/release
curl -L -o data/release/papers_clean.parquet \
  https://github.com/Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation/releases/latest/download/papers_clean.parquet
python -m src.preprocessing.prepare_for_chunking data/release/papers_clean.parquet data/chunk_input.jsonl
python -m src.chunking.cli
python -m src.vectorizing.cli
python -m src.rag.indexer
```

3. Set a Groq API key: `export GROQ_API_KEY=...` (free key at console.groq.com)

## Run

Ask one question:

```bash
python -m src.pipeline.cli "Can an AI model's step-by-step reasoning be trusted?" \
  --papers data/release/papers_clean.parquet
```

Run all 25 benchmark queries for Task #4:

```bash
python -m src.pipeline.cli --benchmark evaluation/benchmark_queries.csv \
  --papers data/release/papers_clean.parquet
```

Answers are saved to `evaluation/results/end_to_end_outputs.jsonl`, one line per query. If the run stops (for example on a Groq rate limit), run the same command again and it continues from the first unanswered query.

`--papers` must be the same corpus the Chroma database was built from. `CombinedRetriever` refuses to start if they don't match.

## Output fields

| Field | Meaning |
|---|---|
| `query_id`, `category`, `expected_paper_ids` | copied from the benchmark CSV (benchmark mode only) |
| `query` | the question |
| `summary` | generated answer |
| `sources` | retrieved papers: `paper_id`, `title`, `arxiv_url`, `chunk_id`, `section`, `score` |
| `citation_check.cited` | paper IDs the summary cites (version endings removed) |
| `citation_check.cited_not_retrieved` | should be empty; anything here is a made-up citation |
| `citation_check.retrieved_not_cited` | retrieved papers the summary didn't use |

## Using it from code

```python
from src.pipeline.llm import GroqLLM
from src.pipeline.pipeline import answer_query
from src.rag.combined_retriever import CombinedRetriever

retriever = CombinedRetriever(papers_path="data/release/papers_clean.parquet")
llm = GroqLLM()

result = answer_query("How can companies check AI models for bias?", retriever, llm)
print(result["summary"])
```

`answer_query` accepts any retriever with `search(query, top_k)` and any LLM with `generate(system_prompt, user_prompt)`, so a different vector store or prompt can be swapped in without changing the pipeline. The tests in `tests/test_pipeline.py` use fakes for both and need no database or API key.

## Known limitations

- The output is a research summary (objective, methodology, findings, limitations), not business implications yet. Business translation is #27/#28.
- Each paper contributes its abstract plus one chunk, so the summarizer sees limited detail.
- Lakshmee's prompt was tested on one paper at a time. Retrieval returns five, so the quality of multi-paper summaries still needs reviewing in Task #4.
- The citation check only verifies that a cited paper was retrieved, not that the claim is actually in that paper.
