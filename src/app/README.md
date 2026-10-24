# Consultant web UI

A local web page where consultants ask a question and get a cited business brief, with the research summary and sources beside it. It runs the same pipeline as `src/pipeline/cli.py` (LanceDB combined retriever, summarization, business translation).

## Run it

```bash
pip install -r requirements.txt
export NVIDIA_API_KEY=nvapi-...         # free trial key at build.nvidia.com
python -m src.app                       # then open http://localhost:8000
```

It needs the papers in `data/papers_clean.parquet` and the LanceDB index built from them in `data/index` (see `src/pipeline/README.md`, Setup). Startup takes a few seconds to load the embedding model. Paper title/abstract vectors are read from the index; if it was built before they were stored, they're embedded at startup instead, which takes longer.

Options: `--provider nvidia|groq|gemini` (default `nvidia`), `--model`, `--reasoning-effort` (`none` for models that reject it), `--port`, `--papers`, `--index-dir`, `--briefs-dir`.

## What each button costs

| Action | LLM calls |
|---|---|
| Generate brief | 2 (summary, then brief) |
| Rewrite for another audience | 1 (reuses the saved summary) |
| Regenerate brief (after "Request changes") | 1 |
| Open a saved brief, approve, request changes, copy link, export PDF | 0 |

Every answer is saved as a JSON file in `data/ui_briefs/` (git-ignored), so reopening a brief never calls the LLM again.

## Pages

- **Ask:** question, audience (Executive, Risk & compliance, Technical lead), papers per answer, benchmark example questions, and recent briefs with their review status.
- **Brief:**
  - The review banner (Approve / Request changes with a note).
  - Automatic checks:
    - Every cited paper was retrieved.
    - The brief has all six template sections and fewer than 200 words.
    - The evidence rating.
    - Whether the model output was cut off.
  - The brief and research summary tabs, with numbered citations linked to the sources sidebar.

## Files

| File | What it does |
|---|---|
| `server.py` | FastAPI app (`create_app`) and the `python -m src.app` entry point |
| `store.py` | Saves and lists briefs as JSON files |
| `checks.py` | Citation, template and evidence checks (no LLM) |
| `static/` | The page: `index.html`, `app.css`, `app.js` (no build step) |

Tests: `tests/test_app.py` (uses a fake retriever and LLM, so no API key is needed).
