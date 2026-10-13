# Research Paper Summarization — October Milestone

Contributor: Lakshmee  
Milestone: October Milestone #2 — Task 2: Integrate Summarization Capabilities  
Branch: `lakshmee-summarization`  
Status: Summarization prompt, model selection, API testing, and evaluation completed. Full RAG pipeline integration is being handled separately.

## 1. Overview

This component generates structured summaries of retrieved arXiv research-paper content for our AI Research Intelligence Agent.

The goal is to turn retrieved research chunks into clear summaries that answer a user's research question while keeping the findings accurate and supported by the original research.

Each summary follows four sections:

- Research Objective: What problem is the paper trying to solve?
- Methodology: What approaches, models, datasets, or experiments were used?
- Key Findings: What were the main results and conclusions?
- Limitations: What limitations or uncertainties were identified?

The prompt also requires citations identifying the source papers and instructs the model not to invent findings or fill in missing information.

## 2. Implementation

### A. Two-Shot Summarization Prompt

File: `src/summarization/prompts.py`

I created a two-shot prompt that includes:

- A system prompt explaining the summarizer's role and accuracy requirements.
- Two example research excerpts and their expected summaries.
- Examples based on arXiv papers `2609.38107v1` and `2609.38108v1`.
- A consistent four-section output format.
- Instructions to only use retrieved research content.
- Requirements for accurate technical names, numerical results, and citations.
- Instructions to acknowledge missing information instead of guessing.

After the first round of testing, I updated the prompt to be more specific about preserving exact model names, method names, statistics, and source-supported limitations.

### B. Reusable Prompt-Building Function

Function: `build_summarization_prompt(query, retrieved_chunks)`

File: `src/summarization/prompts.py`

The function accepts two inputs:

- `query`: The user's research question.
- `retrieved_chunks`: Research-paper excerpts provided by the retrieval pipeline, including source identifiers.

It returns a formatted user prompt containing the two examples, the research question, the retrieved content, and instructions for generating a summary.

This function only prepares the prompt. The actual summary is generated when the prompt is passed to an LLM.

### C. Test Preparation Script

File: `prepare_summarization_tests.py`

I created a script that:

- Loads research chunks from `data/chunks.parquet`.
- Selects three arXiv papers for testing.
- Uses the first 8 chunks from each paper.
- Formats the research content with paper identifiers.
- Calls `build_summarization_prompt()` to prepare the test prompts.
- Saves the generated prompts under `reports/summarization/`.

I chose 8 chunks per paper to keep the test inputs manageable and make it easier to compare summaries with their sources. This also let me test chunk-based input, which is how the summarizer will receive research content from the RAG pipeline.

The three papers used for testing were:

| Paper ID | Research Paper |
|---|---|
| `2609.38043v1` | UserProxyBench |
| `2609.38070v1` | Divergent Token Confidence |
| `2609.38166v1` | LeapQuant |

### D. Model Selection and Summarization Test Script

File: `tests/test_summarization.py`

I selected `openai/gpt-oss-120b` through the Groq API to generate summaries.

The test script:

- Connects to Groq using the `GROQ_API_KEY` environment variable.
- Reads the prepared two-shot prompts.
- Uses `SUMMARIZATION_SYSTEM_PROMPT` as the system instruction.
- Generates a summary for each of the three test papers.
- Saves the results in the v2 results folder.

The model uses a temperature of `0.1` and a maximum of `1500` completion tokens.

The API key is read from the environment and is not hardcoded into the script.

## 3. Testing and Evaluation

I completed two rounds of testing on the same three papers.

For each paper, I compared the generated summary with the retrieved research chunks and checked:

- Whether the research objective and methodology were accurate.
- Whether the numerical results matched the source.
- Whether technical names were preserved correctly.
- Whether the citations referenced the correct papers.
- Whether the model included unsupported claims or limitations.

### Initial Testing (v1)

All three papers generated summaries in the required format.

| Research Paper | Result | Findings |
|---|---|---|
| UserProxyBench | Mostly Passed | Main findings and statistics were supported, but the model used `Gemma-3.5-Flash` instead of `Gemini-3.5-Flash` and included some inferred limitations. |
| Divergent Token Confidence | Mostly Passed | Main calibration results were accurate, but the model used `DTC_count` instead of `DTC_lin`. Some methodology points also lacked citations. |
| LeapQuant | Passed for Reviewed Claims | Main methods and numerical results were supported by the retrieved content. |

### Updated Prompt Testing (v2)

I revised the prompt to include stricter instructions about technical terminology, numerical accuracy, citations, and unsupported limitations. I then retested all three papers.

| Research Paper | Result | Findings |
|---|---|---|
| UserProxyBench | Partially Passed | The model correctly selected `Gemma-31B` at a fidelity threshold of 0.84 but incorrectly selected it again at 0.86 instead of `Gemini-3.5-Flash`. |
| Divergent Token Confidence | Partially Passed | Main calibration results remained accurate, but the estimator names were generated as `DTClin` and `DTCprod` instead of `DTC_lin` and `DTC_prod`. |
| LeapQuant | Passed for Reviewed Claims | Main methodology and numerical results remained accurate in the reviewed claims. |

Overall, the summaries preserved most of the main findings, but both testing rounds showed issues with exact technical terminology. The v2 test also included one incorrect model-to-result relationship.

The full comparison, specific errors, and recommended improvements are documented in `reports/summarization/evaluation.md`.

## 4. File Structure

The main files for this component are organized as follows:

```text
src/
└── summarization/
    ├── __init__.py
    ├── prompts.py
    └── README.md

data/
└── summarization_examples/
    ├── 2609.38107v1.txt
    └── 2609.38108v1.txt

tests/
└── test_summarization.py

prepare_summarization_tests.py

reports/
└── summarization/
    ├── evaluation.md
    ├── 2609.38043v1_prompt.txt
    ├── 2609.38070v1_prompt.txt
    ├── 2609.38166v1_prompt.txt
    ├── summarization_prompt_v1_results/
    │   ├── 2609.38043v1_summary_before.md
    │   ├── 2609.38070v1_summary_before.md
    │   └── 2609.38166v1_summary_before.md
    └── summarization_prompt_v2_results/
        ├── 2609.38043v1_summary.md
        ├── 2609.38070v1_summary.md
        └── 2609.38166v1_summary.md
```

The prompt files contain the prepared research inputs. The v1 and v2 folders contain the actual summaries generated during each testing round.

## 5. How to Reproduce the Tests

Run the following commands from the repository root.

### Step 1: Install Dependencies

Make sure Python is installed and the required packages are available.

```powershell
python -m pip install openai pandas pyarrow
```

### Step 2: Set the Groq API Key

The test script requires a Groq API key stored as an environment variable.

In PowerShell:

```powershell
$env:GROQ_API_KEY = "YOUR_GROQ_API_KEY"
```

Do not commit API keys or other secrets to GitHub.

### Step 3: Prepare the Test Prompts

Make sure `data/chunks.parquet` is available, then run:

```powershell
python prepare_summarization_tests.py
```

This generates the three prepared prompt files in `reports/summarization/`.

### Step 4: Generate Summaries

Run:

```powershell
python tests/test_summarization.py
```

The script generates summaries for all three papers and saves them in:

`reports/summarization/summarization_prompt_v2_results/`

Note: Running the script again will overwrite the existing v2 summaries. The original v1 summaries are saved separately for comparison.

### Step 5: Review the Evaluation

The testing results and source comparisons are documented in:

`reports/summarization/evaluation.md`

This includes the initial results, retesting results, factual errors, and recommended improvements.

## 6. How Teammates Can Use the Prompt

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

When connecting the prompt to an LLM:

- Use `SUMMARIZATION_SYSTEM_PROMPT` as the system instruction.
- Use the result of `build_summarization_prompt()` as the user prompt.
- Pass both to the selected model through its API.

The test script demonstrates this process using GPT-OSS-120B through Groq.

The current implementation uses paper-ID citations. The citation format should be aligned with the team's final retrieval and citation conventions during integration.

## 7. Integration Considerations

The summarization prompt and model testing are complete, but connecting the component to the full RAG pipeline is separate work.

The remaining integration work includes:

- Connecting retrieved chunks directly to the summarization function.
- Confirming the shared input and output format.
- Aligning paper citations with the team's citation validation process.
- Handling inputs that exceed the model's context limits.
- Adding checks for technical names and numerical findings.

The current test script reads prepared prompt files and calls Groq. It does not yet run the complete retrieval-to-summarization pipeline.

## 8. Completion Status

| Deliverable | Status |
|---|---|
| Two-shot summarization prompt | Complete |
| Reusable prompt-building function | Complete |
| Three test cases prepared | Complete |
| Model selection (GPT-OSS-120B through Groq) | Complete |
| Groq API testing script | Complete |
| Initial summaries (v1) | Complete |
| Updated prompt and retesting (v2) | Complete |
| Evaluation against retrieved research | Complete |
| Evaluation report | Complete |
| Full RAG pipeline integration | Pending — separate team work |

## 9. Final Handoff

The two-shot summarization prompt, model testing script, generated summaries, and evaluation report are complete.

The prompt can be imported using `build_summarization_prompt(query, retrieved_chunks)`, and the Groq test script provides an example of how to generate summaries using the selected model.

The evaluation shows that the model generally preserves the main research findings but can still make mistakes with technical names and model-to-result relationships. These issues are documented in `evaluation.md` and should be considered when connecting the summarization component to the full RAG pipeline.