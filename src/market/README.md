# market

The logic behind the **market scan**: what public companies say in their SEC filings about the technology a brief's research covers, and where that points to growth for client industries and for our firm. The web routes are in `src/app/market.py`, the prompt is in `src/translation/market_prompts.py`, and the full user guide is in `src/app/README.md` (Market scan).

## Files

| File | What it does |
|---|---|
| `edgar.py` | `EdgarClient`: talks to SEC EDGAR full-text search. Searches filings, counts how many mention a phrase, and downloads filing text. Waits 0.15 seconds between requests to stay under SEC's limit of 10 a second. |
| `scan.py` | Builds a scan: suggests search phrases, collects filings, pulls out the relevant sentences, and checks the finished scan |

## How a scan is built (`scan.py`)

1. **Search phrases** (`suggest_phrases`): suggested from the question, summary and paper titles with simple rules, no AI call. The consultant can edit them, up to 4.
2. **Demand signals** (`demand_signals`): how many filings mention each phrase in the chosen window (30, 90 or 180 days) compared with the same dates a year earlier. EDGAR counts these, not the AI. Cited as `[D1]`, `[D2]`...
3. **Filings** (`collect_filings`): up to 8 filings, one per company, from annual and quarterly reports, current reports, 20-F, S-1 and press releases. Optionally only one industry (Technology, Healthcare, Finance, Construction & Real Estate, or Government & Public Services). Cited as `[F1]`, `[F2]`...
4. **Excerpts** (`excerpts`): from each filing, the sentences that mention the phrase, with two sentences either side.
5. **One AI call** writes the scan (prompt in `src/translation/market_prompts.py`).
6. **Checks** (`check_scan`, no AI): every citation points to a real source, every number appears in a source, and companies named in filings are treated as evidence, not as sales targets.

## Setup

SEC EDGAR is free and needs no account, but SEC asks every caller to give a name and contact email:

```bash
export SEC_USER_AGENT="KPMG 1J research prototype you@school.edu"
```

You can also put it in the `.env` file at the repo root. Without it, the Market tab shows setup steps instead of the form.

## Privacy

Only the search phrases and an industry word are sent to SEC. Client names and project details never leave the app.

## Tests

`tests/test_market.py` uses a fake EDGAR and a fake AI, so it needs no keys or internet:

```bash
python -m pytest tests/test_market.py -q
```
