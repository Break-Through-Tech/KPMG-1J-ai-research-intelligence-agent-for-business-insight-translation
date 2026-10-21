# Task 2: Two-Shot Summarization Evaluation

## 1. Implementation and Testing Setup

For Task 2, I developed a two-shot summarization prompt that generates structured summaries from retrieved research-paper content. I used two example papers and their expected summaries to show the model what the output should look like.

I selected GPT-OSS-120B through the Groq API as the language model. The prompt instructs the model to only use retrieved research content, include citations, and avoid making up information.

I tested the prompt on three arXiv research papers:

| Paper ID | Research Paper |
|---|---|
| 2609.38043v1 | UserProxyBench |
| 2609.38070v1 | Divergent Token Confidence |
| 2609.38166v1 | LeapQuant |

For each paper, I used the first 8 retrieved chunks instead of the entire paper to keep the input manageable and make source comparisons easier. I also wanted to test the prompt with chunk-based input, since that is how our RAG pipeline will pass research content to the summarizer.

The expected output included four sections: Research Objective, Methodology, Key Findings, and Limitations.

I evaluated each summary by comparing it with the retrieved chunks. I checked factual accuracy, technical names, numerical results, citations, and unsupported claims.

After the first round of testing, I updated the prompt to address the errors I found. I then retested all three papers using the same retrieved content.

## 2. Initial Testing Results

The first round successfully generated summaries for all three papers. Each summary followed the required four-section structure and included the main research findings.

However, I identified a few issues when comparing the summaries with their sources.

| Research Paper | Result | Findings |
|---|---|---|
| UserProxyBench | Mostly Passed | The main findings and statistics were supported. However, the model wrote `Gemma-3.5-Flash` instead of `Gemini-3.5-Flash`. Some limitations were also inferred rather than directly stated. |
| Divergent Token Confidence | Mostly Passed | The main findings and numerical results were accurate. However, the model used `DTC_count` instead of `DTC_lin`. Some methodology points were missing citations. |
| LeapQuant | Passed for Reviewed Claims | The methodology and performance results matched the retrieved content. No clear factual hallucinations were identified in the reviewed claims. |

The main problems involved incorrect technical terminology and inconsistent citation placement. The model generally preserved the numerical results but sometimes changed specific names.

## 3. Prompt Improvements

Based on the initial testing results, I updated the prompt with more specific accuracy instructions.

The changes included:

- Technical names: Keep model names, method names, and abbreviations exactly as written in the retrieved content.
- Numerical accuracy: Preserve statistics, percentages, and measurements without changing their values.
- Limitations: Only include limitations that are directly supported by the retrieved content.
- Citations: Include the correct paper ID for factual claims.
- Accuracy checks: Check technical terms, numbers, and citations against the research before generating the final response.

I kept the same two-shot prompting approach and four-section output structure. I also updated the example summaries to avoid including unsupported limitations.

## 4. Retesting Results

After updating the prompt, I generated new summaries for all three papers using the same retrieved chunks.

| Research Paper | Result | Findings |
|---|---|---|
| UserProxyBench | Partially Passed | The model correctly identified `Gemma-31B` as the cheapest qualifying proxy at a fidelity threshold of 0.84. However, it incorrectly selected the same model at 0.86 instead of `Gemini-3.5-Flash`. |
| Divergent Token Confidence | Partially Passed | The main findings and calibration results remained accurate. However, the model changed the estimator names to `DTClin` and `DTCprod` instead of `DTC_lin` and `DTC_prod`. |
| LeapQuant | Passed for Reviewed Claims | The methodology and numerical results remained consistent with the source. No clear factual hallucinations were identified in the reviewed claims. |

### UserProxyBench: Incorrect Model Selection

The updated summary incorrectly stated that `Gemma-31B` was the cheapest qualifying model at a fidelity threshold of 0.86.

The retrieved research provided the following results:

| Required Fidelity | Cheapest Qualifying Model |
|---|---|
| 0.75 | GPT-4.1-mini |
| 0.84 | Gemma-31B |
| 0.86 | Gemini-3.5-Flash |

The model correctly explained the overall cost–fidelity comparison but assigned the wrong model to one of the thresholds. This changed the meaning of the reported finding.

The retest also included limitations about generalizability and variability across runs. These were reasonable concerns but were not explicitly presented as limitations in the provided excerpts.

### Divergent Token Confidence: Incorrect Estimator Names

In the initial test, the model used `DTC_count` instead of the correct estimator name, `DTC_lin`.

After updating the prompt, the model generated `DTClin` and `DTCprod`. These were closer to the correct names but still did not match the original research.

The correct estimator names are `DTC_lin` and `DTC_prod`.

The main calibration findings and numerical results remained consistent with the source. The remaining issue was the model's ability to preserve exact technical terminology.

### LeapQuant: Consistent Results

The LeapQuant summary remained accurate in the reviewed claims after the prompt update.

It correctly described the two main techniques, per-window quantization and Compensator Tokens. It also preserved the reported performance results:

- 100× lower BF16 error and 39× lower INT8 error at 64K tokens.
- 3.4× reduction in state memory traffic.
- Up to 56% reduction in end-to-end memory footprint.
- 2.05–3.70× kernel-level speedup and 1.47× overall speedup.

No clear factual hallucinations were identified in the reviewed LeapQuant summary.

## 5. Overall Accuracy and Hallucination Assessment

Across both rounds of testing, all three summaries followed the required four-section structure. The research objectives, methodologies, and most numerical findings were supported by the retrieved content.

However, the evaluation identified three main issues.

### 1. Incorrect Technical Terminology

The model sometimes changed exact model or method names. This happened in both rounds of testing, even after adding stricter instructions.

### 2. Incorrect Model-to-Result Relationships

In the UserProxyBench retest, the model assigned the wrong proxy to the 0.86 fidelity threshold. This was a factual error because it changed which model the research recommended for that requirement.

### 3. Unsupported Limitations and Citation Inconsistencies

The DTC and LeapQuant summaries correctly stated when limitations were not available in the provided excerpts. However, the UserProxyBench summaries included some limitations that were not directly stated.

The summaries generally cited the correct paper IDs, but citation placement was not always consistent. Some factual claims were grouped under a single citation rather than cited individually.

### Formatting Issues

The generated summaries also contained unnecessary Markdown escape characters, such as `**\*\*Research Objective\*\***`.

This did not affect the factual findings, but it made the summaries harder to read. The formatting issue remained after the prompt update.

## 6. Limitations of the Evaluation

- Small test set: Only three research papers were evaluated.
- Partial paper coverage: Each test used eight chunks rather than the full paper. The chunks were selected in their existing order, not ranked by relevance to the question.
- Manual evaluation: The summaries were compared with the retrieved content manually. No automated accuracy or hallucination metric was used.
- Paper-level citations: Individual chunk-level citations were not automatically verified.
- Limited repeat testing: Each paper was generated once with the original prompt and once with the updated prompt. This was not enough to measure consistency across multiple runs.

These limitations mean the results only describe the performance observed in these specific tests.

## 7. Recommended Improvements

| Priority | Improvement | Reason |
|---|---|---|
| High | Validate model and method names against the retrieved content | Both testing rounds included incorrect technical names. |
| High | Verify numerical claims and their associated models or methods | The UserProxyBench retest assigned the wrong model to the 0.86 threshold. |
| Medium | Require direct source support for limitations | Some limitations were inferred rather than explicitly stated. |
| Medium | Improve citation placement and validation | Some claims did not have individual citations. |
| Low | Fix Markdown formatting | Extra escape characters reduced readability. |

The highest priorities are checking exact technical names and verifying that numerical findings are connected to the correct models or methods.