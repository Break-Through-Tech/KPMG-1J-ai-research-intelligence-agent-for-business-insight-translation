# Evaluation Module (`src/evaluation/`)

This module manages automated RAG pipeline evaluation workflows using framework metrics such as RAGAS.

---

## 1. Workflows (`ragas_eval.py`)

- **Purpose**: Evaluates RAG pipeline outputs across key dimensions (e.g., faithfulness, answer relevance, context precision, context recall).
- **Key Components**:
  - `evaluate_rag_pipeline(...)`: Runs evaluation batches on generated answers and context chunks, compiling quality metrics into benchmark reports.
- **Output Artifacts**: Saves structured performance evaluations to `data/eval_results.csv` or designated output paths.

### Usage / Standalone Execution
To run the evaluation workflow directly:
`python -m src.evaluation.ragas_eval`
