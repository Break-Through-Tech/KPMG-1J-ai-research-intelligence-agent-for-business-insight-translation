# Consultant web UI

A local web page where consultants ask a question and get a cited business brief, with the research summary and sources beside it. It runs the same pipeline as `src/pipeline/cli.py` (LanceDB combined retriever, summarization, business translation).

The look follows the team's KPMG-1J Figma file (Home Page and Research Page frames): KPMG blue `#00338D` sidebar, gradient search hero, DM Sans type. The KPMG name in the sidebar is set in type, not the official logo file.

## Run it

```bash
pip install -r requirements.txt
export NVIDIA_API_KEY=...               # free key from build.nvidia.com
python -m src.app --provider nvidia     # then open http://localhost:8000
```

The team uses NVIDIA. On a Mac you can copy the key and run `export NVIDIA_API_KEY="$(pbpaste)"` so it never appears on screen. Groq and Gemini also work: set `GROQ_API_KEY` or `GEMINI_API_KEY` and pass `--provider groq` or `--provider gemini`.

It needs the papers in `data/papers_clean.parquet` and the LanceDB index built from them in `data/index` (see `src/pipeline/README.md`, Setup). Startup takes a few seconds to load the embedding model. Paper title/abstract vectors are read from the index; if it was built before they were stored, they're embedded at startup instead, which takes longer.

Options: `--provider groq|nvidia|gemini` (default `groq`), `--model`, `--reasoning-effort` (`none` for models that reject it), `--port`, `--papers`, `--index-dir`, `--briefs-dir`, `--projects-dir`, `--adaptations-dir`, `--pilot-plans-dir`, `--comments-dir`.

## What each button costs

| Action | LLM calls |
|---|---|
| Generate brief | 2 (summary, then brief) |
| Rewrite for another audience | 1 (reuses the saved summary) |
| Regenerate brief (after "Request changes") | 1 |
| Follow-up question | 1 (answers from the saved summary, no new search) |
| Open a saved brief, approve, request changes, copy link, copy for email or Slack, export PDF | 0 |
| Create or edit a project, add or remove a brief, filter the Library | 0 |

Every answer is saved as a JSON file in `data/ui_briefs/` (git-ignored), so reopening a brief never calls the LLM again. Projects are saved the same way in `data/ui_projects/` (git-ignored).

A question asked inside a project adds the client details (client, industry, engagement goal and notes, capped at 1,200 characters, roughly 100–300 tokens) to the **brief step only**. Retrieval and the research summary never see them, so the evidence is the same as without a project. The exact client text is saved on the brief, so rewrites and follow-ups use it too, even if the project is edited later.

## Pages

The sidebar links to Home, Projects, Research (the most recent brief), Library and Review Queue (with a count of briefs waiting).

- **Home** (`#/`): question, audience (Executive, Risk & compliance, Technical lead), filters, papers per answer, benchmark example questions, how it works, and recent briefs.
  - **Published:** Any time, Last 7 days, Last 14 days, or Since a date. "Last 7 days" counts back from the newest indexed paper, not from today.
  - **Topics:** the most common arXiv primary categories (AI, Language, Vision…). None selected means all.
  - Filters go to the retriever as `{"since", "until", "categories"}` (`src/rag/lance_retriever.py`, `clean_filters`) and are saved with the brief.
  - **Project** (shown once a project exists): file the new brief in a project and tailor it to that client. It defaults to the project you last opened.
- **Projects** (`#/projects`): one project per client engagement, with name, client, industry, engagement goal and notes. Archived projects are hidden unless you tick "Show archived projects".
  - **Project page** (`#/project/<id>`): the same question box as Home (briefs asked here are tailored to the client and saved in the project), the project's briefs (Remove takes a brief out of the project but keeps it in the Library), **Add a saved brief**, and the client details with **Edit details** (`#/project/<id>/edit`, which also archives or restores).
  - A brief can be in several projects. The brief page lists its projects, with × to remove and **Add to project…** to file it in another.
- **Brief** (`#/brief/<id>`, or `#/brief/<id>/review` to open a tab): status and evidence badges, the question, the Bottom Line as a subtitle, and four tabs:
  - **Brief:** the brief with the evidence meter, cited sources beside it, and the buttons: Export PDF, Copy for email, Copy for Slack, Copy link, Rewrite for another audience. A warning shows here if a citation check failed or the output was cut off.
  - **Follow-up questions** (under the brief): answered from the research summary only, with citations. If the summary doesn't cover it, the answer starts "Not covered:" and offers **Search new papers for this**, which fills in Home.
  - **Research summary:** the summary the brief was written from.
  - **Sources:** every retrieved paper, cited or not, with its arXiv link.
  - **Review:** automatic checks (every cited paper was retrieved; six template sections under 200 words; evidence rating; output not cut off) and the reviewer decision (Approve / Request changes with a note / Regenerate).
- **Library** (`#/library`): every saved brief, with the projects each one is in. Filter by question text, audience, review status, evidence level, date created (last 7, 30 or 90 days) and project (including "Not in a project"). Filtering happens in the page, with no extra requests.
- **Review Queue** (`#/review`): briefs not yet approved.

Copy for email and Copy for Slack turn citations into `[1]`, `[2]` numbers and add a source list with arXiv links. A brief that isn't approved is marked "Draft, awaiting KPMG review. Not for client use."

## Files

| File | What it does |
|---|---|
| `server.py` | FastAPI app (`create_app`) and the `python -m src.app` entry point |
| `store.py` | Saves and lists briefs, projects, industry adaptations, pilot plans and comments as JSON files |
| `checks.py` | Citation, template and evidence checks (no LLM) |
| `static/` | The page: `index.html`, `app.css`, `app.js` (no build step) |

API for projects: `GET/POST /api/projects`, `GET/PUT /api/projects/{id}`, `POST /api/projects/{id}/briefs` (`{"brief_id"}`), `DELETE /api/projects/{id}/briefs/{brief_id}`. `POST /api/ask` takes an optional `project_id`, and every brief response includes `projects`.

## Saved industry adaptations, pilot plans and comments

Each is saved as one JSON file (git-ignored), like briefs, and saving, opening, editing or deleting one costs no LLM calls. Each keeps the id of what it came from: brief → adaptations → pilot plans, and comments can sit on any of the three.

| Item | Folder | Fields |
|---|---|---|
| Industry adaptation | `data/ui_adaptations/` | `id`, `brief_id`, `query`, `industry`, `use_cases`, `constraints`, `considerations` (lists of text or small objects), `created_by`, `created_at`, `updated_at` |
| Pilot plan | `data/ui_pilot_plans/` | `id`, `adaptation_id`, `brief_id`, `industry`, `title`, `use_case`, `answers` (question → answer), `checklist` (`[{"text", "done"}]`), `created_by`, `created_at`, `updated_at` |
| Comment | `data/ui_comments/` | `id`, `target_type` (`brief`, `adaptation` or `pilot_plan`), `target_id`, `author`, `text`, `created_at` |

API:

- Adaptations: `POST /api/briefs/{brief_id}/adaptations`, `GET /api/briefs/{brief_id}/adaptations`, `GET /api/adaptations?brief_id=&industry=`, `GET/PUT/DELETE /api/adaptations/{id}`. `GET` one includes its `pilot_plans` and `comments`. Deleting one also deletes its pilot plans and their comments.
- Pilot plans: `POST /api/adaptations/{id}/pilot-plans`, `GET /api/adaptations/{id}/pilot-plans`, `GET /api/pilot-plans?adaptation_id=&brief_id=`, `GET/PUT/DELETE /api/pilot-plans/{id}`. `GET` one includes its `comments`.
- Comments: `POST /api/comments` (`{"target_type", "target_id", "author", "text"}`), `GET /api/comments?target_type=&target_id=` (oldest first), `DELETE /api/comments/{id}`.

`PUT` keeps any field you leave out, so ticking one checklist box can send just `{"checklist": [...]}`. Folders can be changed with `--adaptations-dir`, `--pilot-plans-dir` and `--comments-dir`.

Tests: `tests/test_storage.py` (no API key needed) and `tests/test_app.py` (uses a fake retriever and LLM, so no API key is needed).

## POC Starter

On a brief page, under "Suggested industry applications". The user picks an industry, picks a saved use case or writes one, answers five short questions (who runs it, how long, which records or tools, how they will know it worked, biggest worry) and gets an editable pilot checklist of 8 to 10 steps.

- **One model call** to generate: `POST /api/briefs/{brief_id}/pilot-checklist` (`{"industry", "use_case", "answers"}` returns `{"checklist": [{"text", "done"}]}`). It saves nothing. The prompt reads only the saved research summary and the team's answers, presents every step as a proposal, and marks assumptions with "(assumed)" (`src/translation/poc_prompts.py`).
- **No model calls** to save, tick, edit, reopen or delete. The page saves the plan with the pilot plan routes above. It reuses the saved adaptation for that brief and industry, or creates one holding the use case, because a pilot plan belongs to an adaptation. Ticks and edits are saved as you go with `PUT /api/pilot-plans/{id}`.
- Saved use cases for the chosen industry come from the brief's saved adaptations, so use cases saved by other screens appear as one-click suggestions.

| File | What it does |
|---|---|
| `poc_starter.py` | The checklist route (`add_poc_routes`, called once from `server.py`) |
| `static/poc.js`, `static/poc.css` | The section on the brief page. `app.js` calls `pocStarterSection()` and `bindPocStarter()` |
| `../translation/poc_prompts.py` | The prompt and the parser for the model's reply |

Tests: `tests/test_poc_starter.py` (no API key needed).
