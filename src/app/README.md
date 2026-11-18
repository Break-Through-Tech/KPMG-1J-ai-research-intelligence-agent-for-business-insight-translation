# Consultant web UI

A local web page where consultants ask a question and get a cited business brief, with the research summary and sources beside it. It runs the same pipeline as `src/pipeline/cli.py` (LanceDB combined retriever, summarization, business translation).

The look follows the team's KPMG-1J Figma file (Home Page and Research Page frames): KPMG blue `#00338D` sidebar, gradient search hero, DM Sans type. The KPMG name in the sidebar is set in type, not the official logo file.

## Run it

```bash
pip install -r requirements.txt
export NVIDIA_API_KEY=...               # free key from build.nvidia.com
python -m src.app --provider nvidia     # then open http://localhost:8000
```

**After pulling new changes, run `pip install -r requirements.txt` again, then restart the app.** New features can add packages: Download PowerPoint on the Present tab needs `python-pptx`, and without it the app won't start (`ModuleNotFoundError: No module named 'pptx'`). The server also only picks up new Python code when it starts. Without a restart, the page can show new buttons whose routes return 404.

The team uses NVIDIA. On a Mac you can copy the key and run `export NVIDIA_API_KEY="$(pbpaste)"` so it never appears on screen. Groq and Gemini also work: set `GROQ_API_KEY` or `GEMINI_API_KEY` and pass `--provider groq` or `--provider gemini`.

It needs the papers in `data/papers_clean.parquet` and the LanceDB index built from them in `data/index` (see `src/pipeline/README.md`, Setup). Startup takes a few seconds to load the embedding model. Paper title/abstract vectors are read from the index; if it was built before they were stored, they're embedded at startup instead, which takes longer.

To get the newest papers, run `./scripts/get_latest_data.sh` and restart the app. It downloads the latest published dataset and index (about 1.5 GB) into those two places, and keeps the previous index as `data/index.previous`. The header ("N papers indexed from arXiv, <dates>") counts what the search index holds, read from `data/index/index_manifest.json`, because downloaded papers that aren't embedded yet can't be found. Hover over it to see how many more papers are waiting and when the index was built.

Instead of exporting, you can put the key in a `.env` file at the repo root (`NVIDIA_API_KEY=...`, git-ignored); the app reads it at startup. For the Market tab, also set `SEC_USER_AGENT` (see [Market scan](#market-scan)).

Options: `--provider groq|nvidia|gemini` (default `groq`), `--model`, `--max-tokens`, `--max-retries`, `--reasoning-effort` (`none` for models that reject it); these LLM options are the same as the pipeline CLI's. Also `--port`, `--papers`, `--index-dir`, `--briefs-dir`, `--projects-dir`, `--adaptations-dir`, `--pilot-plans-dir`, `--comments-dir`, `--market-scans-dir`, `--presentations-dir`.

## What each button costs

| Action | LLM calls |
|---|---|
| Generate brief | 2 (summary, then brief) |
| Rewrite for another audience | 1 (reuses the saved summary) |
| Regenerate brief (after "Request changes") | 1 |
| Follow-up question | 1 (answers from the saved summary, no new search) |
| Run a market scan | 1 (plus 15-25 free SEC EDGAR requests) |
| Generate notes/slides | 1 (from the saved brief and summary) |
| Open a saved brief, approve, request changes, copy link, copy for email or Slack, export PDF | 0 |
| Create or edit a project, add or remove a brief, filter the Library | 0 |
| Open, approve, copy or delete a saved market scan | 0 |
| Open, edit, copy, download or delete a saved presentation | 0 |

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
  - **Project page** (`#/project/<id>`): the same question box as Home (briefs asked here are tailored to the client and saved in the project), the project's briefs (Remove takes a brief out of the project but keeps it in the Library), **Add a saved brief**, the market scans run on the project's briefs, and the client details with **Edit details** (`#/project/<id>/edit`, which also archives or restores).
  - A brief can be in several projects. The brief page lists its projects, with × to remove and **Add to project…** to file it in another.
- **Brief** (`#/brief/<id>`, or `#/brief/<id>/review` to open a tab): status and evidence badges, the question, the Bottom Line as a subtitle, and six tabs:
  - **Brief:** the brief with the evidence meter, cited sources beside it, and the buttons: Generate notes/slides (opens the Present tab), Export PDF, Copy for email, Copy for Slack, Copy link, Rewrite for another audience. A warning shows here if a citation check failed or the output was cut off.
  - **Follow-up questions** (under the brief): answered from the research summary only, with citations. If the summary doesn't cover it, the answer starts "Not covered:" and offers **Search new papers for this**, which fills in Home.
  - **Research summary:** the summary the brief was written from.
  - **Sources:** every retrieved paper, cited or not, with its arXiv link.
  - **Market:** a market scan from SEC filings (see [Market scan](#market-scan)).
  - **Present:** a slide outline with speaker notes for a chosen audience and talk length (see [Present](#present-notesslides)).
  - **Review:** automatic checks (every cited paper was retrieved; six template sections under 200 words; evidence rating; output not cut off) and the reviewer decision (Approve / Request changes with a note / Regenerate).
- **Library** (`#/library`): every saved brief, with the projects each one is in. Filter by question text, audience, review status, evidence level, date created (last 7, 30 or 90 days), whether it has a market scan, and project (including "Not in a project"). Filtering happens in the page, with no extra requests.
- **Review Queue** (`#/review`): briefs not yet approved.

Copy for email and Copy for Slack turn citations into `[1]`, `[2]` numbers and add a source list with arXiv links. A brief that isn't approved is marked "Draft, awaiting KPMG review. Not for client use."

## Files

| File | What it does |
|---|---|
| `server.py` | FastAPI app (`create_app`) and the `python -m src.app` entry point |
| `store.py` | Saves and lists briefs, projects, industry adaptations, pilot plans and comments as JSON files |
| `checks.py` | Citation, template and evidence checks (no LLM) |
| `static/` | The page: `index.html`, `app.css`, `app.js`, plus `poc.*`, `market.*` and `present.*` for those sections (no build step) |

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

## Market scan

The **Market** tab on a brief page shows what public companies say in their SEC filings about the technology the research covers, and where that points to growth for client industries and for our firm.

```bash
export SEC_USER_AGENT="KPMG 1J research prototype you@school.edu"   # or put it in .env
```

SEC EDGAR is free and needs no account, but SEC asks every caller to name itself with a contact email in the User-Agent header and to stay under 10 requests a second (the client waits 0.15 s between requests). Without `SEC_USER_AGENT` the tab shows these setup steps instead of the form.

How a scan is built (`src/market/scan.py`):

1. **Search phrases:** suggested from the question, summary and paper titles by simple rules, with no LLM call, in the wording filers use ("algorithmic bias", not "AI bias", which has about 1 filing in 90 days). The consultant edits them; up to 4.
2. **Counts** `[D1]...`: filings mentioning each phrase in the window (30, 90 or 180 days) against the same dates a year earlier, counted by EDGAR.
3. **Filings** `[F1]...`: up to 8, one per company, taking turns between phrases. Annual and quarterly reports, current reports (8-K, 6-K), 20-F and S-1, plus press releases (EX-99). Contracts and merger agreements are left out, since they only match through legal definitions of "artificial intelligence". From each, the sentences mentioning the phrase with two either side.
4. **Industry:** filtered by SIC code (Technology, Healthcare, Finance, Construction & Real Estate). Government agencies don't file with the SEC, so Government & Public Services adds the word "government" to the search instead.
5. **One LLM call** (`src/translation/market_prompts.py`) writes seven sections: Market Snapshot, Who's Moving, Demand Signals, Research vs Market, Growth Opportunities, Risks & Headwinds, Watch List. Every claim cites a filing, a count or a paper from the research summary. Risk factors, press releases and business descriptions are described as what they are, and every opportunity is labeled as interpretation with a confidence.
6. **Checks (no LLM):** every citation is one of the scan's sources; every number appears in a filing, a count or the summary; no opportunity is "for" a company named in the filings (companies are evidence, not sales targets, and audit independence rules may apply); at least 3 filings matched.

Only the phrases and an industry word are sent to SEC, never client or project details. A scan is saved in `data/ui_market_scans/` (git-ignored) with all its sources and the date they were retrieved, and goes through the same review as a brief (Approve / Request changes). Running a new scan keeps the old ones, so they can be compared. The project page lists the scans for its briefs, and the Library can filter by "Has a market scan".

| File | What it does |
|---|---|
| `market.py` | The routes (`add_market_routes`, called once from `server.py`) |
| `../market/edgar.py` | SEC EDGAR client: full-text search, counts, filing text |
| `../market/scan.py` | Phrase suggestions, filing selection, excerpts and checks |
| `../translation/market_prompts.py` | The prompt |
| `static/market.js`, `static/market.css` | The Market tab and the project page section |

API: `GET /api/market/options`, `GET /api/briefs/{id}/market-phrases`, `GET/POST /api/briefs/{id}/market-scans` (POST `{"phrases", "industry", "lens": "client"|"firm"|"both", "window_days"}`), `GET /api/market-scans?project_id=`, `GET/DELETE /api/market-scans/{id}`, `POST /api/market-scans/{id}/status`.

Tests: `tests/test_market.py` (fake EDGAR and LLM, no keys or network needed).

## Present (notes/slides)

**Generate notes/slides** on the Brief tab opens the **Present** tab (`#/brief/<id>/present`). It turns the brief into a slide outline the consultant can present from.

1. Pick who you're presenting to: Executive, Risk & Compliance, Technical Lead or Consultant Team. It defaults to the brief's audience. Consultant Team exists only here, so briefs are unchanged.
2. Pick 5, 10 or 20 minutes (about 4, 7 or 11 slides).
3. Optionally include a saved industry adaptation, pilot plan or market scan for this brief. This adds an "Industry or pilot plan" slide.
4. **One LLM call** (`src/translation/present_prompts.py`) writes the slides in a fixed storyline: The answer, Why it matters, Research findings, What to do next, Evidence and limitations, Industry or pilot plan, Sources. Each slide has a title, bullets, conversational speaker notes, minutes, and 1-2 likely audience questions with suggested answers. The deck also lists things to watch out for. If the research doesn't answer a likely question, the suggested answer says so.

The prompt allows only facts, numbers and paper IDs from the brief, the research summary, the sources and the included saved work. It also forbids merging results across studies or turning a benchmark result into a business outcome. After generating, and again after every edit, `check_deck` (no LLM) flags:
- paper IDs that weren't retrieved or that the summary doesn't cite
- numbers that appear in none of the inputs
- slides without notes, bullets or a title, a missing Sources slide, and minutes that don't add up to the talk length

The checks don't catch every wrong claim, so the deck is always labeled a draft. If the brief isn't approved, the tab and **Copy as text** say so.

Slides are edited in place and save automatically, with no LLM call. Decks are saved in `data/ui_presentations/` (git-ignored). Generating again keeps the older decks, which can be reopened from the saved list. **Download PowerPoint** saves the deck, edits included, as a `.pptx`. It has a title slide, one slide per outline slide, and a presenter-only Watch out for slide. The speaker notes, planned minutes and likely questions go in each slide's notes, so they show in Presenter View. If the brief isn't approved, the title slide says it's a draft. **Copy as text** gives the same outline as plain text. Neither calls the LLM.

| File | What it does |
|---|---|
| `present.py` | The routes (`add_present_routes`, called once from `server.py`) and `check_deck` |
| `present_pptx.py` | `build_pptx`: the PowerPoint download (`python-pptx`) |
| `../translation/present_prompts.py` | Audiences, talk lengths, the prompt and `parse_deck` |
| `static/present.js`, `static/present.css` | The Present tab |

API: `GET /api/present/options`, `GET/POST /api/briefs/{id}/presentations` (POST `{"audience", "minutes", "adaptation_id"?, "pilot_plan_id"?, "market_scan_id"?}`; GET also lists the saved work that can be included), `GET/PUT/DELETE /api/presentations/{id}` (PUT `{"slides", "watch_outs"}`), `GET /api/presentations/{id}/pptx`.

Tests: `tests/test_present.py` (fake LLM, no keys needed).
