# Consultant web UI

A local web page where consultants ask a question and get a cited business brief, with the research summary and sources beside it. It runs the same pipeline as `src/pipeline/cli.py` (LanceDB combined retriever, summarization, business translation).

The look follows the team's KPMG-1J Figma file (Home Page and Research Page frames): KPMG blue `#00338D` sidebar, gradient search hero, DM Sans type. The KPMG name in the sidebar is set in type, not the official logo file.

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
| Follow-up question | 1 (answers from the saved summary, no new search) |
| Open a saved brief, approve, request changes, copy link, copy for email or Slack, export PDF | 0 |

Every answer is saved as a JSON file in `data/ui_briefs/` (git-ignored), so reopening a brief never calls the LLM again.

## Pages

The sidebar links to Home, Research (the most recent brief), Library and Review Queue (with a count of briefs waiting).

- **Home** (`#/`): question, audience (Executive, Risk & compliance, Technical lead), filters, papers per answer, benchmark example questions, how it works, and recent briefs.
  - **Published:** Any time, Last 7 days, Last 14 days, or Since a date. "Last 7 days" counts back from the newest indexed paper, not from today.
  - **Topics:** the most common arXiv primary categories (AI, Language, Vision…). None selected means all.
  - Filters go to the retriever as `{"since", "until", "categories"}` (`src/rag/lance_retriever.py`, `clean_filters`) and are saved with the brief.
- **Brief** (`#/brief/<id>`, or `#/brief/<id>/review` to open a tab): status and evidence badges, the question, the Bottom Line as a subtitle, and four tabs:
  - **Brief:** the brief with the evidence meter, cited sources beside it, and the buttons: Export PDF, Copy for email, Copy for Slack, Copy link, Rewrite for another audience. A warning shows here if a citation check failed or the output was cut off.
  - **Follow-up questions** (under the brief): answered from the research summary only, with citations. If the summary doesn't cover it, the answer starts "Not covered:" and offers **Search new papers for this**, which fills in Home.
  - **Research summary:** the summary the brief was written from.
  - **Sources:** every retrieved paper, cited or not, with its arXiv link.
  - **Review:** automatic checks (every cited paper was retrieved; six template sections under 200 words; evidence rating; output not cut off) and the reviewer decision (Approve / Request changes with a note / Regenerate).
- **Library** (`#/library`) and **Review Queue** (`#/review`): saved briefs; the queue shows those not yet approved.

Copy for email and Copy for Slack turn citations into `[1]`, `[2]` numbers and add a source list with arXiv links. A brief that isn't approved is marked "Draft, awaiting KPMG review. Not for client use."

## Files

| File | What it does |
|---|---|
| `server.py` | FastAPI app (`create_app`) and the `python -m src.app` entry point |
| `store.py` | Saves and lists briefs as JSON files |
| `checks.py` | Citation, template and evidence checks (no LLM) |
| `static/` | The page: `index.html`, `app.css`, `app.js` (no build step) |

Tests: `tests/test_app.py` (uses a fake retriever and LLM, so no API key is needed).
