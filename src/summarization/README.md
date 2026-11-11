# summarization

Step 1 of the answer: the prompt that turns the retrieved paper text into a **research summary**. Step 2 (`src/translation`) then turns that summary into a business brief.

## What the summary looks like

Exactly four sections, with a paper ID cited for every factual claim:

| Section | What it says |
|---|---|
| Research Objective | What the papers set out to find |
| Methodology | How they tested it |
| Key Findings | What they found, with numbers copied exactly |
| Limitations | Weaknesses the papers themselves state. If none are stated: "The provided research content does not specify limitations." |

## How the prompt works (`prompts.py`)

| Name | What it is |
|---|---|
| `SUMMARIZATION_SYSTEM_PROMPT` | The rules: use only the retrieved content, never invent findings or citations, cite only retrieved papers, copy model names and numbers exactly (Gemini and Gemma are different models), and only list limitations the paper states |
| `FEW_SHOT_EXAMPLES` | Two real arXiv papers with a question, the source text and a model summary. They teach the format; the prompt says never to reuse their findings. |
| `build_summarization_prompt(query, retrieved_chunks)` | Builds the full prompt: the two examples, then the question and the retrieved paper text, then a short checklist of accuracy rules |
| `SUMMARIZATION_SYSTEM_PROMPT_COMPACT` | A shorter version with one example (`compact=True`), about 750 instead of 1,430 tokens. Off by default; see the comparison in `src/pipeline/README.md`. |

The retrieved paper text comes from `format_retrieved_content` in `src/pipeline/pipeline.py`: each paper's ID, title, abstract, best matching passage, and its results and limitations passages.

## Why it's built this way

- **Facts first, interpretation second.** The summary only reports what the papers say. Business advice happens in step 2, so each step can be checked on its own.
- **Few-shot examples** keep the four-section format consistent across questions.
- **Citations by paper ID** let `check_citations` (in `src/pipeline/pipeline.py`) flag any cited paper that was never retrieved.

## Use it

```python
from src.summarization.prompts import SUMMARIZATION_SYSTEM_PROMPT, build_summarization_prompt

prompt = build_summarization_prompt("Can AI reasoning traces be trusted?", retrieved_text)
summary = llm.generate(SUMMARIZATION_SYSTEM_PROMPT, prompt)
```

In practice `answer_query` in `src/pipeline/pipeline.py` does this for you.
