# End-to-End Pipeline (Task #3: Connect Retrieval + Summarization)

Takes a question in plain English and returns a cited summary of the relevant research, plus a business brief that says what it means and what to do.

```
question
  -> LanceCombinedRetriever (src/rag/lance_retriever.py)  top 5 papers + best supporting chunk each
  -> ContextCompressor (compress.py, with --compress)     optional: shortens the passages, no LLM call
  -> format_retrieved_content                             paper ID, title, abstract, section, chunk text
  -> build_summarization_prompt (src/summarization)       Lakshmee's two-shot prompt
  -> LLM (Groq openai/gpt-oss-120b, or NVIDIA / Gemini)  4-section summary with [paper_id] citations
  -> check_citations                                      flags cited papers that were never retrieved
  -> build_business_prompt (src/translation)              reads ONLY the summary, never the paper text
  -> LLM (same model)                                     6-section business brief with [paper_id] citations
  -> check_citations                                      also flags brief citations the summary didn't make
```

## Business brief (#27 / #28)

The second step turns the research summary into a brief with six sections, in the same format as the gold examples in `src/evaluation/gold_standard_examples.md` (on `main`). It stays under 200 words:

| Section | What it says |
|---|---|
| Bottom Line | 1-2 plain-English sentences answering the question, or saying the research doesn't answer it |
| Why It Matters | business impact (risk, cost, compliance, trust), each point tied to a cited finding |
| What To Do | up to 3 concrete actions that follow from the findings |
| Evidence Strength | High / Medium / Low and why (number of papers, lab benchmark vs real-world, models tested) |
| Caveat | the summary's limitations, restated as business risks |
| Sources | the paper IDs cited in the brief |

It is a separate step, not a longer summary prompt, so the facts (step 1) and the interpretation (step 2) can be checked on their own. Step 2 only sees the summary, so it can't pick up anything step 1 didn't say, and its prompt is about 1.3k tokens instead of 5-7k. The prompt forbids numbers, ROI figures or papers that aren't in the summary, and asks for implications to be worded as interpretation.

`--audience` changes the focus: `executive` (default, decisions and business risk), `risk` (controls, governance, monitoring) or `technical` (what to build or test, how mature the methods are). `--no-translate` skips the brief, which halves the LLM calls per question.


## Files

| File | Purpose |
|---|---|
| `pipeline.py` | `answer_query()`, `run_benchmark()`, formatting and citation check |
| `compress.py` | `ContextCompressor`: shortens the paper text before the summary call |
| `llm.py` | `LLM` client for Groq (default, same model and settings as the summarization testing), NVIDIA or Gemini |
| `cli.py` | command line entry point |

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Get the corpus and the LanceDB search index (`src/indexing`):

```bash
mkdir -p data
curl -L -o data/papers_clean.parquet \
  https://github.com/Break-Through-Tech/KPMG-1J-ai-research-intelligence-agent-for-business-insight-translation/releases/latest/download/papers_clean.parquet
```

If that release also lists `index.tar.gz`, download it from the same release and unpack it (`tar -xzf index.tar.gz -C data`). Otherwise build the index (one time, about 20 minutes on a laptop CPU):

```bash
python -m src.preprocessing.prepare_for_chunking
python -m src.chunking.cli
python -m src.indexing.cli
```

The index and `--papers` must come from the same release. The retriever refuses to start if the index has papers the corpus file doesn't.

3. Set an API key, one of:
   - Groq (default): `export GROQ_API_KEY=...`, key at console.groq.com. With the results and limitations passages a summary prompt is about 9,000–12,000 tokens, more than Groq's free tier allows per minute (8,000), so use a paid Groq plan or one of the providers below if requests are rejected as too large.
   - NVIDIA: `export NVIDIA_API_KEY=nvapi-...`, free trial key at build.nvidia.com, then add `--provider nvidia` to the commands below. The default model is `nvidia/nemotron-3-ultra-550b-a55b` (about 2 minutes a question, careful with numbers and citations); `--model openai/gpt-oss-20b` is faster (about 20 seconds) but less careful. If a model rejects `reasoning_effort`, add `--reasoning-effort none`.
   - Gemini: `export GEMINI_API_KEY=...`, free key at aistudio.google.com, then add `--provider gemini` to the commands below. Answers from a different model aren't directly comparable with the Groq benchmark runs, so save them to their own `--output` file.

## Run

Ask one question:

```bash
python -m src.pipeline.cli "Can an AI model's step-by-step reasoning be trusted?"
```

Run all 25 benchmark queries for Task #4:

```bash
python -m src.pipeline.cli --benchmark evaluation/benchmark_queries.csv
```

Answers are saved to `evaluation/results/end_to_end_outputs.jsonl`, one line per query. If the run stops (for example on a rate limit), run the same command again and it continues from the first unanswered query.

Rate limits: free tiers limit requests or tokens per minute (Gemini's free tier allows 5 requests a minute), so when a request is rate limited the pipeline waits as long as the provider asks and retries, up to `--max-retries` times (default 5). A **daily** limit stops the run with a message instead, because waiting minutes won't help; rerun later, use another key, or switch `--provider`. To avoid hitting the per-minute limit at all, add a pause between questions, e.g. `--delay 26` for Gemini's 5 requests a minute (each question makes two requests; `--delay 13` with `--no-translate`).

Retrievers (`--retriever`), both on the LanceDB index:

| Option | How it ranks papers |
|---|---|
| `lance-combined` (default) | Thania's CombinedRetriever method: title/abstract search and hybrid chunk search, merged with reciprocal rank fusion |
| `lance` | Hybrid (vector + keyword) chunk search only, grouped into papers |

See `evaluation/results/retriever_comparison.md` for how they compare with the earlier Chroma retriever.

Other options: `--top-k` (papers per answer, default 5), `--max-tokens` (default 4096) and `--reasoning-effort` (`low`/`medium`/`high`, default `low`). gpt-oss-120b's hidden reasoning counts toward `--max-tokens`, so at the original 1500 most 5-paper summaries were cut off. To re-run the benchmark with new settings, pass a new `--output` file; otherwise the run skips queries that are already answered.

## Shortening the paper text (`compress.py`)

The summary prompt carries each paper's title, abstract, best chunk, and its results and limitations passages: about 7,900 tokens of paper text on the benchmark questions. With `--compress`, `ContextCompressor` trims it before the summary call, without an LLM. **It is off by default**: in the comparison below it cut the prompt by 4% without accuracy problems, but answers took longer (25 s to 42 s on average) and total tokens didn't go down.

1. **Repeated text:** neighbouring chunks of one section share about 200 characters, and passages can repeat the abstract; each is kept once.
2. **Cleanup:** citation markers (`[12]`, `(Smith et al., 2025)`), URLs, LaTeX commands and markdown noise. Numbers and tables stay.
3. **Sentences:** the sentences closest to the question (by the same embedding model) with **two sentences either side**, plus **every sentence with a number or a caveat** ("however", "only", "fails", "limitation"...) with one either side. Gaps are marked `[...]`, and the prompt is told not to connect statements across them.
4. **Budget by rank** (`--context-budget`, default 8,000 estimated tokens): titles and abstracts always go in, then every paper's best chunk, then limitations passages, then results passages, higher-ranked papers first. A results passage goes last when the paper's best chunk is already from its results.

Its settings are the accuracy-first ones the team chose. Measured on the 24 benchmark questions with `python -m evaluation.compare_context` (no API key needed):

| Settings | Paper-text tokens | Numbers kept | Caveat sentences kept | Passages dropped per question |
|---|---|---|---|---|
| No compression | 7,913 | 100% | 100% | 0 |
| **`--compress` settings: keep every number and caveat, budget 8,000** | **7,352 (-7%)** | **90%** | **95%** | **0.6 results** |
| Same, budget 7,000 | 6,679 (-16%) | 77% | 85% | 2.2 results |
| Numbers and caveats only in the more relevant half, 1 sentence of context, budget 6,000 | 5,645 (-29%) | 73% | 65% | 1.3 results |
| Budget 5,000 | 4,812 (-39%) | 31% | 45% | 2.9 limitations, 3.8 results |

Research text has a number or a caveat in most sentences, so keeping all of them keeps most of the text; larger savings only come from dropping facts. With `--compress`, each answer saves `context` (`tokens_before`, `tokens_after`, what was `dropped`); without it, `context` is `null`.

`--compact-prompt` uses shorter summarization instructions with one example instead of two (about 750 instead of 1,430 tokens, `SUMMARIZATION_SYSTEM_PROMPT_COMPACT` in `src/summarization/prompts.py`). It is off by default because of the comparison below.

### Comparison with the real model

`python -m evaluation.compare_context --llm --provider nvidia --questions Q10,Q11,Q12,Q13,Q14,Q15` wrote one summary per question with each version (Nemotron Ultra, Nov 10 2026; results in `evaluation/results/context_compression_llm.*`). Averages over the 6 questions, token counts as reported by the API:

| Version | Prompt tokens | Output tokens (incl. hidden reasoning) | Total | Seconds | Problems |
|---|---|---|---|---|---|
| Full (no compression, full instructions) | 8,127 | 1,506 | 9,633 | 25 | none new |
| Compressed (`--compress`) | 7,821 (-4%) | 2,040 | 9,860 | 42 | none |
| Compressed + `--compact-prompt` | 7,194 (-11%) | 2,829 | 10,022 | 57 | one summary cut off at the token limit; one number misstated ("true accuracy 0.51-0.52" where the paper says 0.52 confidence) |

- No version cited a paper it hadn't retrieved. Five decimals in the Q10 summaries aren't in the paper text in any version, including the uncompressed one, so they don't come from compression.
- The prompts got shorter, but the model's hidden reasoning got longer, so total tokens didn't go down in this sample. The visible summaries were about the same length (~670-780 tokens). With one run per question this could be chance; more questions and repeat runs would tell.
- The shorter instructions are not ready: they produced the only accuracy error.

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
| `business_insight` | `null` with `--no-translate` or when nothing was retrieved, otherwise the fields below |
| `business_insight.audience` | `executive`, `risk` or `technical` |
| `business_insight.brief` | the business brief |
| `business_insight.truncated` | `true` if the brief was cut off |
| `business_insight.citation_check.cited_not_in_summary` | should be empty; papers the brief cites that the summary didn't |

## Using it from code

```python
from src.pipeline.llm import LLM
from src.pipeline.pipeline import answer_query
from src.rag.lance_retriever import LanceCombinedRetriever

retriever = LanceCombinedRetriever()  # data/papers_clean.parquet and data/index
llm = LLM()  # Groq by default, or LLM(provider="nvidia") / LLM(provider="gemini")

result = answer_query("How can companies check AI models for bias?", retriever, llm)
print(result["summary"])
```

`answer_query` accepts any retriever with `search(query, top_k)` and any LLM with `generate(system_prompt, user_prompt)`, so a different vector store or prompt can be swapped in without changing the pipeline. The tests in `tests/test_pipeline.py` use fakes for both and need no database or API key.

## Known limitations

- The business brief format and prompt are a first draft for #27/#28 and haven't been reviewed by the team or scored yet.
- Each question now makes two LLM calls (summary + brief), so free-tier limits are reached about twice as fast. Use `--no-translate` for retrieval/summary-only benchmark runs.
- The citation checks only verify that a cited paper was retrieved (and, for the brief, cited in the summary), not that the claim is actually in that paper.
- Each paper contributes its abstract plus one chunk, so the summarizer sees limited detail.
- Lakshmee's prompt was tested on one paper at a time. Retrieval returns five, so the quality of multi-paper summaries still needs reviewing in Task #4.
