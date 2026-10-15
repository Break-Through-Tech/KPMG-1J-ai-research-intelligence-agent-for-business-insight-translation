# End-to-End Pipeline (Task #3: Connect Retrieval + Summarization)

Takes a question in plain English and returns a cited summary of the relevant research.

```
question
  -> LanceCombinedRetriever (src/rag/lance_retriever.py)  top 5 papers + best supporting chunk each
  -> format_retrieved_content                             paper ID, title, abstract, section, chunk text
  -> build_summarization_prompt (src/summarization)       Lakshmee's two-shot prompt
  -> LLM (Groq openai/gpt-oss-120b, or Gemini)            4-section summary with [paper_id] citations
  -> check_citations                                      flags cited papers that were never retrieved
```

## Files

| File | Purpose |
|---|---|
| `pipeline.py` | `answer_query()`, `run_benchmark()`, formatting and citation check |
| `llm.py` | `LLM` client for Groq (default, same model and settings as the summarization testing) or Gemini |
| `cli.py` | command line entry point |

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Get the corpus and the LanceDB search index (`src/indexing`):

```bash
mkdir -p data/release
curl -L -o data/release/papers_clean.parquet \
  https://github.com/Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation/releases/latest/download/papers_clean.parquet
```

If that release also lists `index.tar.gz`, download it from the same release and unpack it (`tar -xzf index.tar.gz -C data`). Otherwise build the index (one time, about 20 minutes on a laptop CPU):

```bash
python -m src.preprocessing.prepare_for_chunking data/release/papers_clean.parquet data/chunk_input.jsonl
python -m src.chunking.cli
python -m src.indexing.cli
```

The index and `--papers` must come from the same release. The retriever refuses to start if the index has papers the corpus file doesn't.

3. Set an API key, either:
   - Groq (default): `export GROQ_API_KEY=...`, free key at console.groq.com
   - Gemini: `export GEMINI_API_KEY=...`, free key at aistudio.google.com, then add `--provider gemini` to the commands below. Answers from a different model aren't directly comparable with the Groq benchmark runs, so save them to their own `--output` file.

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

Retrievers (`--retriever`), both on the LanceDB index:

| Option | How it ranks papers |
|---|---|
| `lance-combined` (default) | Thania's CombinedRetriever method: title/abstract search and hybrid chunk search, merged with reciprocal rank fusion |
| `lance` | Hybrid (vector + keyword) chunk search only, grouped into papers |

See `evaluation/results/retriever_comparison.md` for how they compare with the earlier Chroma retriever.

Other options: `--top-k` (papers per answer, default 5), `--max-tokens` (default 4096) and `--reasoning-effort` (`low`/`medium`/`high`, default `low`). gpt-oss-120b's hidden reasoning counts toward `--max-tokens`, so at the original 1500 most 5-paper summaries were cut off. To re-run the benchmark with new settings, pass a new `--output` file; otherwise the run skips queries that are already answered.

## Output fields

| Field | Meaning |
|---|---|
| `query_id`, `category`, `expected_paper_ids` | copied from the benchmark CSV (benchmark mode only) |
| `query` | the question |
| `summary` | generated answer |
| `truncated` | `true` if the LLM hit its token limit and the summary is cut off; re-run with a higher `--max-tokens` |
| `sources` | retrieved papers: `paper_id`, `title`, `arxiv_url`, `chunk_id`, `section`, `score` |
| `citation_check.cited` | paper IDs the summary cites (version endings removed) |
| `citation_check.cited_not_retrieved` | should be empty; anything here is a made-up citation |
| `citation_check.retrieved_not_cited` | retrieved papers the summary didn't use |

## Using it from code

```python
from src.pipeline.llm import LLM
from src.pipeline.pipeline import answer_query
from src.rag.lance_retriever import LanceCombinedRetriever

retriever = LanceCombinedRetriever(papers_path="data/release/papers_clean.parquet")
llm = LLM()  # or LLM(provider="gemini")

result = answer_query("How can companies check AI models for bias?", retriever, llm)
print(result["summary"])
```

`answer_query` accepts any retriever with `search(query, top_k)` and any LLM with `generate(system_prompt, user_prompt)`, so a different vector store or prompt can be swapped in without changing the pipeline. The tests in `tests/test_pipeline.py` use fakes for both and need no database or API key.

## Known limitations

- The output is a research summary (objective, methodology, findings, limitations), not business implications yet. Business translation is #27/#28.
- Each paper contributes its abstract plus one chunk, so the summarizer sees limited detail.
- Lakshmee's prompt was tested on one paper at a time. Retrieval returns five, so the quality of multi-paper summaries still needs reviewing in Task #4.
- The citation check only verifies that a cited paper was retrieved, not that the claim is actually in that paper.
