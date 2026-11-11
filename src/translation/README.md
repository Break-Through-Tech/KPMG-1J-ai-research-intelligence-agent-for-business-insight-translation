# translation

Step 2 of the answer, plus the app's other writing tasks: the prompts that turn a saved **research summary** (from `src/summarization`) into business-friendly output. Every prompt here reads the summary, never the raw paper text, so it can't add facts the summary didn't state.

## Files

| File | Used for |
|---|---|
| `prompts.py` | Business brief, follow-up questions, client context, industry applications |
| `poc_prompts.py` | POC Starter pilot checklist |
| `market_prompts.py` | Market scan from SEC filings |

## Business brief (`prompts.py`)

The brief has six sections (`BUSINESS_SECTIONS`) and stays short:

| Section | What it says |
|---|---|
| Bottom Line | 1–2 plain sentences answering the question, or saying the research doesn't answer it |
| Why It Matters | Business impact (risk, cost, compliance, trust), each point tied to a cited finding |
| What To Do | Up to 3 concrete actions that follow from the findings |
| Evidence Strength | High / Medium / Low and why |
| Caveat | The summary's limitations, restated as business risks |
| Sources | The paper IDs cited |

The format matches the human-written examples in `src/evaluation/gold_standard_examples.md`.

| Name | What it does |
|---|---|
| `BUSINESS_SYSTEM_PROMPT` | Rules for the brief: only use the summary, no numbers, ROI figures or papers it doesn't contain, word implications as interpretation |
| `AUDIENCES` | Who the brief is for: `executive` (default: decisions, risk, cost, trust), `risk` (controls, governance, monitoring), `technical` (what to build or test, how mature the methods are) |
| `FEW_SHOT_EXAMPLES` | Two example briefs that show the format |
| `build_business_prompt(query, summary, audience, client)` | Builds the brief prompt |
| `format_client_context(project)` | Adds a project's client, industry, goal and notes (up to 1,200 characters) so Why It Matters and What To Do fit that client. The client details are never treated as evidence. |
| `FOLLOWUP_SYSTEM_PROMPT`, `build_followup_prompt(...)` | Answers a follow-up question from the saved summary and the last 3 follow-ups. If the summary doesn't cover it, the answer starts with "Not covered:". |
| `INDUSTRY_APPLICATION_SYSTEM_PROMPT`, `build_industry_application_prompt(summary, industry)` | A 120–170 word recommendation for a director in a chosen industry: Proposed workflow, Implementation, Safeguards, Pilot. Written as a proposal, never as something the research tested. |

## POC Starter checklist (`poc_prompts.py`)

| Name | What it does |
|---|---|
| `POC_CHECKLIST_SYSTEM_PROMPT` | Writes 8–10 pilot steps for one use case: access to tools and records, measuring today's process, a small first run, who reviews output, the success measure, a safeguard for the biggest worry, and a final expand/change/stop step. Assumptions are marked "(assumed)". |
| `build_poc_checklist_prompt(summary, industry, use_case, answers)` | Adds the industry, use case and the team's answers. Blank answers are sent as "Not answered". |
| `parse_checklist(text)` | Turns the model's reply into `[{"text", "done"}]` items (3 to 12 steps, each up to 300 characters) for the saved pilot plan |

## Market scan (`market_prompts.py`)

| Name | What it does |
|---|---|
| `MARKET_SECTIONS` | Market Snapshot, Who's Moving, Demand Signals, Research vs Market, Growth Opportunities, Risks & Headwinds, Watch List |
| `MARKET_SCAN_SYSTEM_PROMPT` | Rules: cite every claim as a filing `[F#]`, a filing count `[D#]` or a paper ID; use numbers only from a cited source; say what kind of statement each filing is (risk factor, press release, business description) |
| `LENS_FOCUS` | Where to look for growth: the client's industry, our firm's services, or both |
| `build_market_scan_prompt(query, summary, gathered, industry, lens)` | Builds the prompt from the summary and the filings gathered by `src/market/scan.py` |

## Why it's a separate step

- The summary step sticks to facts; this step interprets them. Keeping them apart means each can be checked on its own.
- The input is a short summary instead of 5–7k tokens of paper text, so each of these calls is cheap.
- `check_citations` in `src/pipeline/pipeline.py` also flags brief citations that the summary didn't make.
