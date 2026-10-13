# Research Paper Summarization — October Milestone

**Contributor:** Lakshmee  
**Milestone:** October Milestone #2 — Task 2: Integrate Summarization Capabilities  
**Branch:** `lakshmee-summarization`  
**Status:** Prompt implementation and test-input preparation completed; LLM integration and evaluation pending.

## 1. Overview

This component is designed to summarize retrieved arXiv research-paper content as part of our AI Research Intelligence Agent.

The goal is to turn retrieved research chunks into structured, evidence-grounded summaries that answer a user's research question while minimizing hallucinations.

Each generated summary should include four sections:

1. **Research Objective:** What problem is the paper trying to solve?
2. **Methodology:** What approaches, models, datasets, or experiments were used?
3. **Key Findings:** What were the main results and conclusions?
4. **Limitations:** What limitations or uncertainties were identified?

Summaries must be grounded in the retrieved research content and include citations identifying the source papers.

## 2. My Contributions So Far

### A. Two-shot summarization prompt

**File:** `src/summarization/prompts.py`

Implemented a two-shot prompt template containing:

- A system instruction defining the summarizer's role and evidence-grounding rules.
- Two example research questions, source excerpts, and expected summaries.
- Examples based on arXiv papers `2609.38107v1` and `2609.38108v1`.
- A consistent four-section output structure.
- Instructions to avoid invented findings, statistics, or unsupported claims.
- Instructions to acknowledge missing information rather than guessing.
- Source citation requirements.

The prompt is designed to work with retrieved research chunks, rather than requiring a complete research paper as input.

### B. Reusable prompt-building function

**Function:** `build_summarization_prompt(query, retrieved_chunks)`

**File:** `src/summarization/prompts.py`

The function accepts:

- `query`: The user's research question.
- `retrieved_chunks`: Research-paper excerpts retrieved by the RAG pipeline, including source identifiers.

It returns a formatted prompt containing the two examples, the user's question, the retrieved evidence, and instructions for generating the summary.

**Important:** This function constructs the prompt. It does not call an LLM or generate a summary by itself.

### C. Test-input preparation script

**File:** `prepare_summarization_tests.py`

Created a script that:

1. Loads existing research-paper chunks from `data/chunks.parquet`.
2. Selects three arXiv papers for initial testing.
3. Extracts the first eight available chunks for each paper.
4. Formats the selected research content with source information.
5. Calls `build_summarization_prompt()` to create the two-shot prompts.
6. Saves the prompts as text files for later LLM testing.

**Prepared test papers:**

| Paper ID | Research topic |
|---|---|
| `2609.38043v1` | AI agent benchmarking |
| `2609.38070v1` | Model uncertainty |
| `2609.38166v1` | Efficient language models |

The script executed successfully and prepared all three prompt files.

### D. Generated test inputs

**Folder:** `reports/summarization/`

- `2609.38043v1_prompt.txt`
- `2609.38070v1_prompt.txt`
- `2609.38166v1_prompt.txt`

These files contain the prepared two-shot prompts and retrieved paper excerpts. They are **not LLM-generated summaries**.

## 3. How to Reproduce the Test Preparation

From the repository root, install the required dependencies in your Python environment, including `pandas` and a Parquet reader such as `pyarrow`.

Ensure the following files are available:

- `src/summarization/prompts.py`
- `prepare_summarization_tests.py`
- `data/chunks.parquet`

Run:

```powershell
python prepare_summarization_tests.py
```

Expected output:

```text
Prepared: reports\summarization\2609.38043v1_prompt.txt
Source chunks: 8
Prepared: reports\summarization\2609.38070v1_prompt.txt
Source chunks: 8
Prepared: reports\summarization\2609.38166v1_prompt.txt
Source chunks: 8
All available test prompts prepared!
```

The script uses specific paper IDs and expects the current Parquet column names. If the dataset schema changes, update the script accordingly.

## 4. How Teammates Can Use the Prompt

The prompt-building function can be imported into the summarization component:

```python
from src.summarization.prompts import (
    SUMMARIZATION_SYSTEM_PROMPT,
    build_summarization_prompt,
)

query = "How do researchers evaluate AI agent reliability?"

retrieved_chunks = """
[2609.38108v1] Example research evidence from retrieval...
"""

user_prompt = build_summarization_prompt(
    query,
    retrieved_chunks
)
```

When connecting an LLM, use:

- `SUMMARIZATION_SYSTEM_PROMPT` as the system instruction.
- The result of `build_summarization_prompt()` as the user prompt.

Pass both to the selected model using its provider's API.

**Integration considerations:**

- Alena will handle passing retrieved chunks into the summarization step and preserving source citations.
- Grace will coordinate the shared data/output format.
- Olivia will handle citation validation and arXiv link formatting.
- Thania will help handle retrieved content that exceeds model input limits.

The prompt should be checked against the team's agreed citation format. For example, if retrieval uses numbered citations such as `[1]`, the model's output should follow that convention instead of inventing new references.

## 5. Remaining Work

### A. Confirm the LLM

**Status:** Pending team confirmation.

Determine:

- Which LLM provider and model the team will use.
- Whether an API key is already available.
- Which SDK or API integration is already being used elsewhere in the repository.

Do not commit API keys or secrets to GitHub.

### B. Run real summarization tests

Once the LLM is selected:

1. Create or adapt a script to call the model using the existing prompt.
2. Run the three prepared test cases.
3. Save the actual generated summaries.
4. Compare each summary with its source paper.
5. Expand to five papers if time permits.

The current preparation script does not perform these steps.

### C. Evaluate accuracy and hallucinations

Review each generated summary for:

- Correct research objective.
- Accurate methodology.
- Supported key findings.
- Accurate limitations.
- Valid source citations.
- Unsupported claims or fabricated statistics.

Document any errors and revise the prompt as needed.

### D. Complete pipeline integration

Coordinate with Alena and Grace to confirm the expected input structure, output format, and citation conventions.

## 6. Current Completion Status

| Deliverable | Status |
|---|---|
| Two-shot summarization prompt | Complete |
| Prompt-building function | Complete |
| Three test cases prepared | Complete |
| Model selection | Pending |
| LLM API integration | Pending |
| Generated summaries | Pending |
| Evaluation against source papers | Pending |
| End-to-end integration | Owned by other teammates |

## 7. Next Steps

After the team confirms its LLM provider:

1. Connect the existing prompt to the selected model.
2. Generate summaries for the three prepared papers.
3. Review outputs against the original paper content.
4. Document results and any prompt improvements.
5. Share the finalized prompt interface with the pipeline integration team.

**Current handoff:** The prompt and three test inputs are ready for model integration. No LLM-generated summary quality claims have been made yet.