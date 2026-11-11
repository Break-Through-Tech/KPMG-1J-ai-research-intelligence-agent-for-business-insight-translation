# Market scan routes (the Market tab on the brief page). Running a scan reads
# SEC EDGAR (about 15-25 requests, no account) and makes one LLM call; opening,
# reviewing or deleting a saved scan costs nothing.
#
# GET    /api/market/options                  industries, lenses, windows, whether EDGAR is set up
# GET    /api/briefs/{id}/market-phrases      suggested search phrases (no LLM)
# GET    /api/briefs/{id}/market-scans        saved scans for a brief
# POST   /api/briefs/{id}/market-scans        run a scan {phrases, industry, lens, window_days}
# GET    /api/market-scans?project_id=        saved scans for every brief in a project
# GET    /api/market-scans/{id}               one scan
# POST   /api/market-scans/{id}/status        {status, note}: approve or request changes
# DELETE /api/market-scans/{id}
#
# Kept in its own file, like poc_starter.py, so it doesn't collide with other
# changes to server.py.

from fastapi import HTTPException
from pydantic import BaseModel

from src.market.edgar import SETUP_MESSAGE, EdgarError
from src.market.scan import (
    DEFAULT_INDUSTRY,
    DEFAULT_LENS,
    DEFAULT_WINDOW,
    INDUSTRIES,
    LENSES,
    MAX_PHRASES,
    WINDOWS,
    check_scan,
    clean_phrases,
    gather,
    suggest_phrases,
)
from src.translation.market_prompts import MARKET_SCAN_SYSTEM_PROMPT, build_market_scan_prompt


class MarketScanRequest(BaseModel):
    phrases: list[str]
    industry: str = DEFAULT_INDUSTRY
    lens: str = DEFAULT_LENS
    window_days: int = DEFAULT_WINDOW


class MarketStatusRequest(BaseModel):
    status: str
    note: str = ""


def add_market_routes(app, load, run_llm, llm, scans, edgar, projects, now,
                      statuses, today=None):
    """
    load:     server.py's load(brief_id), a 404 for an unknown brief
    run_llm:  server.py's run_llm(step), which turns LLM errors into messages
    scans:    a MarketScanStore
    edgar:    an EdgarClient, or None when SEC_USER_AGENT isn't set
    projects: the ProjectStore, for a project's scans
    today:    a function returning today's date (tests pin it)
    """

    def load_scan(scan_id):
        try:
            return scans.load(scan_id)
        except KeyError:
            raise HTTPException(404, "Market scan not found")

    @app.get("/api/market/options")
    def market_options():
        return {
            "configured": edgar is not None,
            "setup": "" if edgar is not None else SETUP_MESSAGE,
            "industries": list(INDUSTRIES),
            "default_industry": DEFAULT_INDUSTRY,
            "lenses": LENSES,
            "default_lens": DEFAULT_LENS,
            "windows": WINDOWS,
            "default_window": DEFAULT_WINDOW,
            "max_phrases": MAX_PHRASES,
        }

    @app.get("/api/briefs/{brief_id}/market-phrases")
    def market_phrases(brief_id: str):
        return {"phrases": suggest_phrases(load(brief_id))}

    @app.get("/api/briefs/{brief_id}/market-scans")
    def brief_market_scans(brief_id: str):
        load(brief_id)
        return scans.list(brief_id=brief_id)

    @app.post("/api/briefs/{brief_id}/market-scans")
    def run_market_scan(brief_id: str, request: MarketScanRequest):
        record = load(brief_id)

        if edgar is None:
            raise HTTPException(503, SETUP_MESSAGE)
        if not record.get("sources"):
            raise HTTPException(400, "This brief has no research summary to scan the market for.")
        if request.industry not in INDUSTRIES:
            raise HTTPException(400, f"Unknown industry {request.industry!r}")
        if request.lens not in LENSES:
            raise HTTPException(400, f"Unknown lens {request.lens!r}")
        if request.window_days not in WINDOWS:
            raise HTTPException(400, f"Choose a window of {', '.join(map(str, WINDOWS))} days.")
        try:
            phrases = clean_phrases(request.phrases)
        except ValueError as error:
            raise HTTPException(400, str(error))

        try:
            gathered = gather(edgar, phrases, request.industry, request.window_days,
                              today=today() if today else None)
        except EdgarError as error:
            raise HTTPException(502, str(error))

        if not gathered["filings"]:
            which = "" if request.industry == DEFAULT_INDUSTRY else f"{request.industry} "
            raise HTTPException(
                404,
                f"No {which}filings in the last {request.window_days} days mention these phrases. "
                "Try broader phrases, a longer window or Cross-industry.",
            )

        prompt = build_market_scan_prompt(record["query"], record["summary"], gathered,
                                          request.industry, request.lens)
        text = run_llm(lambda: llm.generate(MARKET_SCAN_SYSTEM_PROMPT, prompt))

        scan = {
            "id": scans.new_id(),
            "brief_id": brief_id,
            "query": record["query"],
            "created_at": now(),
            "provider": getattr(llm, "provider", ""),
            "model": getattr(llm, "model", ""),
            "phrases": phrases,
            "industry": request.industry,
            "lens": request.lens,
            "window_days": request.window_days,
            "scan": text,
            "truncated": getattr(llm, "last_finish_reason", None) == "length",
            # everything the scan was written from, with when it was retrieved
            "sources": gathered,
            "checks": check_scan(text, gathered, record),
            "status": "draft",
            "note": "",
        }
        return scans.save(scan)

    @app.get("/api/market-scans")
    def project_market_scans(project_id: str):
        try:
            project = projects.load(project_id)
        except KeyError:
            raise HTTPException(404, "Project not found")
        return scans.list(brief_ids=project.get("brief_ids", []))

    @app.get("/api/market-scans/{scan_id}")
    def get_market_scan(scan_id: str):
        return load_scan(scan_id)

    @app.post("/api/market-scans/{scan_id}/status")
    def market_scan_status(scan_id: str, request: MarketStatusRequest):
        if request.status not in statuses:
            raise HTTPException(400, f"Unknown status {request.status!r}")
        scan = load_scan(scan_id)
        scan["status"] = request.status
        scan["note"] = request.note.strip()[:4000]
        scan["reviewed_at"] = now()
        return scans.save(scan)

    @app.delete("/api/market-scans/{scan_id}")
    def delete_market_scan(scan_id: str):
        load_scan(scan_id)
        scans.delete(scan_id)
        return {"deleted": scan_id}
