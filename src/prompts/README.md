# Prompts Module (`src/prompts/`)

This module manages the prompt templates and formatting logic for constructing model inputs in the RAG pipeline.

---

## 1. Templates (`templates.py`)

- **Purpose**: Defines structured prompt templates and utility functions to insert retrieved context chunks and user questions into system-level prompts for the LLM.
- **Key Components**:
  - `RAG_PROMPT_TEMPLATE`: Base prompt string containing explicit instruction guardrails and structural placeholders (`{context}` and `{question}`).
  - `format_rag_prompt(context: str, question: str) -> str`: Formats and injects the context and question strings safely into the template.

### Usage / Standalone Execution
To test prompt formatting directly:
`python -m src.prompts.templates`
