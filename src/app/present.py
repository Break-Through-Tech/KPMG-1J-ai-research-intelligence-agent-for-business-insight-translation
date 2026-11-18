# Present tab routes: turn a saved brief into a slide outline with speaker
# notes, likely questions and things to watch out for. Generating a deck is one
# LLM call; opening, editing or deleting a saved deck costs nothing.
#
# GET    /api/present/options               audiences, talk lengths, defaults
# GET    /api/briefs/{id}/presentations     saved decks for a brief, plus the saved
#                                           materials that can be included
# POST   /api/briefs/{id}/presentations     generate {audience, minutes, adaptation_id?,
#                                           pilot_plan_id?, market_scan_id?}
# GET    /api/presentations/{id}            one deck
# PUT    /api/presentations/{id}            save edits {slides, watch_outs}
# DELETE /api/presentations/{id}
#
# Kept in its own file, like market.py and poc_starter.py, so it doesn't
# collide with other changes to server.py.

import threading

from fastapi import HTTPException
from pydantic import BaseModel

from src.market.scan import _numbers
from src.pipeline.pipeline import CITATION_PATTERN, base_id, check_citations
from src.translation.present_prompts import (
    AUDIENCE_LABELS,
    DEFAULT_LENGTH,
    LENGTHS,
    MAX_SLIDES,
    MAX_WATCH_OUTS,
    PRESENT_AUDIENCES,
    PRESENT_SYSTEM_PROMPT,
    build_present_prompt,
    clean_slide,
    clean_watch_outs,
    deck_text,
    parse_deck,
)

# How far the slides' minutes may add up from the talk length before it's flagged
MINUTES_TOLERANCE = 0.25

# Longest saved material put into the prompt, so one big scan can't crowd out the brief
EXTRA_CHARS = 4000


class PresentRequest(BaseModel):
    audience: str
    minutes: int = DEFAULT_LENGTH
    adaptation_id: str | None = None
    pilot_plan_id: str | None = None
    market_scan_id: str | None = None


class QuestionEdit(BaseModel):
    question: str = ""
    answer: str = ""


class SlideEdit(BaseModel):
    section: str = ""
    title: str = ""
    bullets: list[str] = []
    notes: str = ""
    minutes: float = 0
    questions: list[QuestionEdit] = []


class PresentationEdit(BaseModel):
    slides: list[SlideEdit]
    watch_outs: list[str] = []


# ---------- saved materials as prompt text ----------

def _item(entry):
    if isinstance(entry, dict):
        return "; ".join(f"{k}: {v}" for k, v in entry.items() if v)
    return str(entry)


def adaptation_text(adaptation):
    lines = [f"Industry: {adaptation.get('industry', '')}"]
    for field, label in (("use_cases", "Use cases"), ("constraints", "Business constraints"),
                         ("considerations", "Implementation considerations")):
        items = adaptation.get(field) or []
        if items:
            lines.append(f"{label}:")
            lines += [f"- {_item(i)}" for i in items]
    return "\n".join(lines)[:EXTRA_CHARS]


def pilot_plan_text(plan):
    lines = [
        f"Industry: {plan.get('industry', '')}",
        f"Use case: {_item(plan.get('use_case', ''))}",
    ]
    if plan.get("title"):
        lines.insert(0, f"Title: {plan['title']}")
    answers = plan.get("answers") or {}
    if answers:
        lines.append("Team answers:")
        lines += [f"- {q} {a or 'Not answered'}" for q, a in answers.items()]
    lines.append("Proposed pilot steps (a proposal, not tested by the research):")
    lines += [f"- {step.get('text', '')}" for step in plan.get("checklist", [])]
    return "\n".join(lines)[:EXTRA_CHARS]


def market_scan_text(scan):
    return f"Industry: {scan.get('industry', '')}\n{scan.get('scan', '')}"[:EXTRA_CHARS]


# ---------- checks (no LLM) ----------

def check_deck(deck, record, extras_text, minutes):
    """Citations that point nowhere, numbers in no input, and missing pieces."""
    text = deck_text(deck)
    slides = deck.get("slides", [])

    papers = check_citations(text, record.get("sources", []))
    summary_cited = {base_id(p) for p in record.get("citation_check", {}).get("cited", [])}
    # retrieved papers the summary never cites (made-up ones are reported above)
    not_in_summary = [p for p in papers["cited"]
                      if p not in summary_cited and p not in papers["cited_not_retrieved"]]

    briefs = record.get("briefs", {})
    source_text = " ".join([
        record.get("query", ""),
        record.get("summary", ""),
        " ".join(entry.get("brief", "") for entry in briefs.values()),
        " ".join(s.get("title", "") for s in record.get("sources", [])),
        extras_text,
    ])
    known = _numbers(source_text)
    allowed = {str(minutes), str(len(slides))}
    ungrounded = sorted(
        n for n in _numbers(CITATION_PATTERN.sub("", text))
        if n not in known and n not in allowed
    )

    total = round(sum(float(s.get("minutes") or 0) for s in slides), 1)
    missing_notes = [i + 1 for i, s in enumerate(slides) if not s.get("notes", "").strip()]
    empty = [i + 1 for i, s in enumerate(slides) if not s.get("bullets")]
    untitled = [i + 1 for i, s in enumerate(slides) if not s.get("title", "").strip()]
    has_sources = any("source" in f"{s.get('section', '')} {s.get('title', '')}".lower() for s in slides)
    target = LENGTHS.get(minutes)
    minutes_ok = abs(total - minutes) <= minutes * MINUTES_TOLERANCE

    return {
        "citations": {
            "ok": not papers["cited_not_retrieved"] and not not_in_summary,
            "cited": papers["cited"],
            "not_retrieved": papers["cited_not_retrieved"],
            "not_in_summary": not_in_summary,
        },
        "numbers": {"ok": not ungrounded, "ungrounded": ungrounded},
        "structure": {
            "ok": not missing_notes and not empty and not untitled and has_sources and minutes_ok,
            "missing_notes": missing_notes,
            "empty_slides": empty,
            "untitled_slides": untitled,
            "has_sources_slide": has_sources,
            "slide_count": len(slides),
            "target_slides": target,
            "total_minutes": total,
            "minutes_ok": minutes_ok,
        },
    }


# ---------- routes ----------

def add_present_routes(app, load, run_llm, llm, presentations, adaptations, pilot_plans,
                       market_scans, now):
    """
    load:          server.py's load(brief_id), a 404 for an unknown brief
    run_llm:       server.py's run_llm(step), which turns LLM errors into messages
    presentations: a PresentationStore
    adaptations, pilot_plans, market_scans: the stores of saved materials a deck
                   can include
    """

    lock = threading.Lock()

    def load_deck(deck_id):
        try:
            return presentations.load(deck_id)
        except KeyError:
            raise HTTPException(404, "Presentation not found")

    def load_extra(kind_store, record_id, label, brief_id):
        try:
            item = kind_store.load(record_id)
        except KeyError:
            raise HTTPException(400, f"{label} not found")
        if item.get("brief_id") != brief_id:
            raise HTTPException(400, f"That {label.lower()} belongs to a different brief.")
        return item

    def gather_extras(request, brief_id):
        """[(label, text)] for the prompt, plus what was included, for the deck."""
        extras, included = [], {}
        if request.adaptation_id:
            a = load_extra(adaptations, request.adaptation_id, "Industry adaptation", brief_id)
            extras.append((f"Industry adaptation: {a.get('industry', '')}", adaptation_text(a)))
            included["adaptation"] = {"id": a["id"], "label": a.get("industry", "")}
        if request.pilot_plan_id:
            p = load_extra(pilot_plans, request.pilot_plan_id, "Pilot plan", brief_id)
            label = p.get("title") or _item(p.get("use_case", ""))
            extras.append((f"Pilot plan: {label}", pilot_plan_text(p)))
            included["pilot_plan"] = {"id": p["id"], "label": label}
        if request.market_scan_id:
            s = load_extra(market_scans, request.market_scan_id, "Market scan", brief_id)
            extras.append((f"Market scan: {s.get('industry', '')}", market_scan_text(s)))
            included["market_scan"] = {"id": s["id"], "label": s.get("industry", "")}
        return extras, included

    def extras_text_for(deck):
        """The saved materials' text again, for re-checking an edited deck."""
        parts = []
        for kind, kind_store, to_text in (
            ("adaptation", adaptations, adaptation_text),
            ("pilot_plan", pilot_plans, pilot_plan_text),
            ("market_scan", market_scans, market_scan_text),
        ):
            ref = deck.get("extras", {}).get(kind)
            if ref:
                try:
                    parts.append(to_text(kind_store.load(ref["id"])))
                except KeyError:
                    pass
        return "\n".join(parts)

    @app.get("/api/present/options")
    def present_options():
        return {
            "audiences": [{"id": a, "label": AUDIENCE_LABELS.get(a, a)} for a in PRESENT_AUDIENCES],
            "lengths": [{"minutes": m, "slides": n} for m, n in LENGTHS.items()],
            "default_length": DEFAULT_LENGTH,
        }

    @app.get("/api/briefs/{brief_id}/presentations")
    def brief_presentations(brief_id: str):
        load(brief_id)
        return {
            "presentations": presentations.list(brief_id=brief_id),
            "materials": {
                "adaptations": [
                    {"id": a["id"], "label": a.get("industry", "")}
                    for a in adaptations.list(brief_id=brief_id)
                ],
                "pilot_plans": [
                    {"id": p["id"], "label": p.get("title") or _item(p.get("use_case", ""))}
                    for p in pilot_plans.list(brief_id=brief_id)
                ],
                "market_scans": [
                    {"id": s["id"], "label": f"{s.get('industry', '')} · {(s.get('created_at') or '')[:10]}"}
                    for s in market_scans.list(brief_id=brief_id)
                ],
            },
        }

    @app.post("/api/briefs/{brief_id}/presentations")
    def generate_presentation(brief_id: str, request: PresentRequest):
        record = load(brief_id)

        if request.audience not in PRESENT_AUDIENCES:
            raise HTTPException(400, f"Unknown audience {request.audience!r}")
        if request.minutes not in LENGTHS:
            raise HTTPException(400, f"Choose a talk length of {', '.join(map(str, LENGTHS))} minutes.")
        if not record.get("sources") or not record.get("briefs") or not record.get("summary"):
            raise HTTPException(400, "This brief has no research summary to present.")

        extras, included = gather_extras(request, brief_id)

        # The brief written for this audience if there is one, otherwise the brief's own
        entry = record["briefs"].get(request.audience) or record["briefs"].get(record.get("audience"))
        if not entry:
            entry = next(iter(record["briefs"].values()))

        prompt = build_present_prompt(record["query"], record["summary"], entry["brief"],
                                      record["sources"], request.audience, request.minutes, extras)

        # parse_deck raises a ValueError for an unusable reply, which run_llm
        # turns into a 400 with its message
        deck = run_llm(lambda: parse_deck(llm.generate(PRESENT_SYSTEM_PROMPT, prompt)))

        stamp = now()
        presentation = {
            "id": presentations.new_id(),
            "brief_id": brief_id,
            "query": record["query"],
            "audience": request.audience,
            "minutes": request.minutes,
            "extras": included,
            **deck,
            "checks": check_deck(deck, record, "\n".join(text for _, text in extras), request.minutes),
            # the brief's review status when the deck was made; the page shows the current one
            "brief_status": record.get("status", "draft"),
            "truncated": getattr(llm, "last_finish_reason", None) == "length",
            "provider": getattr(llm, "provider", ""),
            "model": getattr(llm, "model", ""),
            "created_at": stamp,
            "updated_at": stamp,
        }
        return presentations.save(presentation)

    @app.get("/api/presentations/{deck_id}")
    def get_presentation(deck_id: str):
        return load_deck(deck_id)

    @app.put("/api/presentations/{deck_id}")
    def update_presentation(deck_id: str, request: PresentationEdit):
        if len(request.slides) > MAX_SLIDES:
            raise HTTPException(400, f"Too many slides (at most {MAX_SLIDES}).")
        if len(request.watch_outs) > MAX_WATCH_OUTS:
            raise HTTPException(400, f"Too many watch-outs (at most {MAX_WATCH_OUTS}).")

        with lock:
            deck = load_deck(deck_id)
            deck["slides"] = [clean_slide(s.model_dump()) for s in request.slides]
            deck["watch_outs"] = clean_watch_outs(request.watch_outs)
            try:
                record = load(deck["brief_id"])
            except HTTPException:
                record = {}
            deck["checks"] = check_deck(deck, record, extras_text_for(deck), deck.get("minutes"))
            deck["updated_at"] = now()
            presentations.save(deck)
        return deck

    @app.delete("/api/presentations/{deck_id}")
    def delete_presentation(deck_id: str):
        load_deck(deck_id)
        presentations.delete(deck_id)
        return {"deleted": deck_id}
