# Evaluation of End-to-End Pipeline

## Summary

We reviewed the benchmark questions through retrieval, research summarization, and business translation. This resulted in 30 source entries, six summaries, and six executive business briefs.

- **Retrieval was generally relevant:** 27/30 source entries were relevant (90%), including 15/30 highly relevant entries (50%).
- **Four of six queries found their expected papers.** Q14 and both Q15 targets were absent, although relevant alternatives were retrieved.
- **All outputs completed without truncation.** Citation-ID checks found no warnings, but this does not establish that every cited claim was supported.
- **Most research findings and numbers were supported.** Important weaknesses were missing qualifications and incomplete coverage of the question.
- **Business translation needs the most attention.** Some briefs changed experimental conditions, overstated benefits, or recommended actions without retaining source warnings.

These are AI-assisted review findings, not independent human validation. They cover six specific questions, not the complete 25-query benchmark.

## Setup

| Setting | Value |
|---|---|
| Pipeline commit | `2ac7d8f2263930490ac19178b50c623739a1399f` |
| Corpus release | `data-2026-10-19-0628` |
| Local index | 129,204 chunks from 4,470 usable papers |
| Retrieval | `LanceCombinedRetriever`: title/abstract search plus hybrid chunk search, combined using RRF |
| Papers per question | 5 |
| Generation | Groq `openai/gpt-oss-120b`; temperature 0.1; max tokens 4096; low reasoning effort |
| Business audience | Executive |

The summaries use each retrieved paper's abstract and one supporting chunk. Business briefs use the question and generated summary, not the original paper text. Q14 reused its saved sources and summary; the later run reused those completed outputs. No prompt changes were made for this baseline.

Q11 and Q12 overlap with the summarization prompt's examples. Keep that overlap visible when discussing performance. The corpus and retrieval system also differ from the earlier 1,220-paper Chroma evaluation; the numbers are not a controlled before/after comparison.

## Files

| File | What to use it for |
|---|---|
| `source_review.csv` | One row per query–paper pair: relevance label, reason, target status, and whether the summary cited it. |
| `summary_review.csv` | One row per question: summary coverage/support, business-brief review, and completion checks. |
| `review_findings.csv` | Specific problems, the evidence used to judge them, and suggested corrections. |
| `q10_test/` through `q15_test/` | Original `sources.json`, `output.json`, and `business_insight.json`, unchanged. |
| `specific_questions_settings.json` | Settings recorded during the run. |

Start with `summary_review.csv`, then use `review_findings.csv` for examples. Source notes refer to the matching paper ID in `sources.json`.

## How we reviewed

We compared the generated content with the exact abstracts and chunks supplied to the model. We did not check the full papers or verify their experimental results independently. Numbers reported by the papers were checked for faithful representation, not independently reproduced.

Source labels follow the existing retrieval framework:

- **2:** highly relevant; the main contribution directly addresses the query's topic.
- **1:** somewhat relevant; useful related evidence but not a direct match.
- **0:** not relevant to the question, even if it discusses AI generally.

A paper did not need to answer every part of a question to earn 2. We did not penalize harmless paraphrasing, selective use of sources, or reasonable business interpretation clearly presented as advice. Unused sources are not automatically an error. Q12 is flagged because a directly answering source was available but the answer relied on a different measure instead.

The output reviews use plain-language judgments rather than inventing a new numerical framework:

- **Direct / Partial:** whether the summary covers the main question or only a related part.
- **Mostly supported:** main findings are supported, with qualifications or corrections noted.
- **Partly supported:** substantial material is supported, but a meaningful explanation is unsupported or misleading.
- **Needs revision:** business claims or recommendations need correction before stakeholder use.
- **Clear / Mostly clear / Needs simplification:** readability for teammates and the intended business audience.

These are review descriptions, not calculated accuracy percentages. No claim-level citation-accuracy ratio was calculated; the automated check tests paper IDs, not whether a claim follows from the cited paper. All review rows are marked AI-assisted and should be checked by a teammate before final reporting.

## Retrieval results

| Query | Relevant papers: labels 1 or 2 | Highly relevant: label 2 | Expected papers found |
|---|---:|---:|---|
| Q10 | 4/5 | 2/5 | Yes; rank 1 |
| Q11 | 5/5 | 2/5 | Yes; rank 1 |
| Q12 | 4/5 | 2/5 | Yes; rank 2 |
| Q13 | 4/5 | 2/5 | Yes; rank 1, as v2 |
| Q14 | 5/5 | 5/5 | No |
| Q15 | 5/5 | 2/5 | Neither target |

Average expected-paper recall is 66.7% across the six queries. Q15 has two targets, so its recall would be 50% if one were found; here it is 0%. Missing an expected paper does not make all alternative results irrelevant.

## What worked and what needs attention

| Query | What worked | Main issue |
|---|---|---|
| Q10 | Direct answer with supported 15.2-point and premature-disclosure findings. | Brief turns 24.4% of successful episodes into a statement about evaluations generally, and overstates the simulator-versus-agent comparison. |
| Q11 | Correctly reports that answer correctness and trace validity can diverge. | Brief changes shuffling tokens in 10% of sentences into shuffling 10% of tokens. |
| Q12 | Retrieves the directly answering declared-plan paper. | Summary omits that paper's 22–45% plan-preservation result; task success is then used as evidence of plan adherence. |
| Q13 | Clear account of differing gender-bias patterns and ongoing auditing. | Some proposed actions are reasonable business advice but were not tested by the cited research. |
| Q14 | Relevant alternatives and mostly accurate numerical findings. | Brief misreads an oracle comparison as a requirement and recommends probes the source warns can be unreliable. |
| Q15 | Useful approaches with mostly supported performance figures. | Mixes model memory, token use, and experience storage, while losing some hardware and baseline conditions. |

## What to improve in the prompts

1. **Use the papers that best answer the question.** For Q12, the pipeline retrieved a paper about whether agents follow their declared plans, but the summary left out its main findings.

2. **Keep the conditions attached to each result.** Explain what was tested and what it was compared with. For example, “24.4% of successful episodes” should not become “24.4% of all evaluations.”

3. **Include important limits mentioned in the source text.** These may include testing only one model or finding that results depend on hardware. If business deployment was not discussed, say that the provided evidence does not establish business performance.

4. **Separate research findings from business suggestions.** A method that worked in an experiment is something a company could test—not a guarantee of the same benefits. Avoid recommending a method without mentioning the problems the research found with it.

5. **Explain technical terms in plain language.** A business reader should understand the main finding and its implications without already knowing terms such as AUROC or GRPO.

Keep the current outputs as the **baseline**. When testing revised prompts, use the same saved source text, model, and generation settings. Save the new outputs separately so we can compare them with the originals.

The team should review generated findings and business implications before they are used.
