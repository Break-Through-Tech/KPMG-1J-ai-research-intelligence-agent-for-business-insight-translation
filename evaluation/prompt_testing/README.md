# Business Prompt Testing

## Purpose

Develop and test a prompt for clear, relevant, business-friendly insights from research summaries. The existing business briefs were often technical and sometimes overstated what the research supported.

## Selected prompt

`business_prompt_v2.py` contains the selected second attempt, matching the saved run in `results/prompt_v2/`. It uses clearer instructions for preserving findings, separating research from business suggestions, and acknowledging missing evidence. Section word budgets aim to keep the brief concise.

The original five headings and audience options are retained. The user prompt reuses Chythra's original examples, with a wording change that distinguishes limitations missing from the summary from limitations absent from the research. This version does not use the later fictional example. The production prompt in `src/translation/prompts.py` is unchanged.

## How it was tested

We generated executive briefs for Q12, Q14, and Q15 using the same saved research summaries as the baseline. Retrieval and research summaries were not regenerated. We compared accuracy, relevance, readability, and recommendations against those summaries and the original briefs.

| Setting | Value |
|---|---|
| Pipeline used for the experiment | Chythra's pipeline, commit `2ac7d8f2263930490ac19178b50c623739a1399f` |
| Provider/model | Groq `openai/gpt-oss-120b` |
| Temperature | 0.1 |
| Maximum completion tokens | 4096 |
| Reasoning effort | Low |
| Audience | Executive |

The research summaries came from the earlier end-to-end evaluation using release `data-2026-10-19-0628`. Several local prompt revisions were explored; this folder contains only the selected attempt. 

## Results

| Query | Baseline words | Selected prompt words |
|---|---:|---:|
| Q12 | 357 | 274 |
| Q14 | 408 | 257 |
| Q15 | 477 | 345 |

Counts include headings and citations. All three briefs completed without truncation and had no citation-ID warnings.

The selected prompt produced shorter, more focused briefs, but accuracy improvements were mixed:

- **Q12 — Do agents follow their stated plans?** The brief uses task-completion rates to answer this question. But completing a task and following a stated plan are different things. The research summary also leaves out relevant findings, so changing the business prompt alone cannot fully fix the answer.
- **Q14 — Can companies trust AI confidence scores?** The revised brief removes two misleading recommendations from the original. However, it still tells companies to adopt a method before establishing whether it fits their needs. It also claims the research excluded large commercial systems, which the supplied summary does not establish.
- **Q15 — Can long-context models use fewer resources?** The brief combines different memory, storage, and token savings into a general cost-saving claim that the summary does not support. It also changes “81–85% fewer tokens” into “81–85% of current token use.” The first means a large reduction; the second means keeping most of the original usage.

This is an experimental baseline, not a demonstrated accuracy improvement. Citation-ID checks do not establish that every cited claim is supported. Three development questions are insufficient to establish consistent performance on unseen questions or other audiences.

## Files

- `business_prompt_v2.py`: selected system instructions and user-prompt builder.
- `run_prompt_comparison.py`: runner used for testing, adjusted only to put the six JSON files together in `outputs/`.
- `results/prompt_v2/settings.json`: model settings and prompt/input hashes.
- `results/prompt_v2/system_prompt.txt`: exact system prompt used.
- `results/prompt_v2/outputs/`: inputs and generated briefs for the three questions. Each input includes the query, research summary, original brief, source records, and exact user prompt. Only the query and summary are provided as new evidence to the model; original briefs and source records support review.

## Running the experiment

Run from the pipeline worktree, where `src.pipeline` and `src.translation` are available. The experiment folder alone does not install the pipeline. It also requires the saved Q12/Q14/Q15 baseline folders under `evaluation/benchmark_queries.csv`, project dependencies, and `GROQ_API_KEY` in the local environment.

```bash
python -m evaluation.prompt_testing.run_prompt_comparison
```

Existing outputs are skipped. Changed settings, prompts, or inputs cause the runner to stop rather than mix experiments. Use a new output folder for a new test. Generating a missing brief makes an API call. No new retrieval or index build is needed.

For exact reproduction, retain the pipeline version above; the selected builder imports its original examples. Even with fixed settings, a fresh model response can differ. Treat the saved briefs as the record of this run.
