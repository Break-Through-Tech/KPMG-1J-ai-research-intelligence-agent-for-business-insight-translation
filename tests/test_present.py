import json

import pytest
from fastapi.testclient import TestClient

from src.app.present import check_deck
from src.app.server import create_app
from src.app.store import (
    AdaptationStore,
    BriefStore,
    MarketScanStore,
    PilotPlanStore,
    PresentationStore,
)
from src.translation.present_prompts import (
    BULLET_CHARS,
    MAX_BULLETS,
    PRESENT_AUDIENCES,
    build_present_prompt,
    parse_deck,
)

from tests.test_app import BRIEF, SUMMARY, CountingLLM
from tests.test_pipeline import FakeRetriever, make_papers


def slide(title, section="", bullets=("A point.",), notes="Say this.", minutes=2, questions=()):
    return {"section": section or title, "title": title, "bullets": list(bullets), "notes": notes,
            "minutes": minutes, "questions": list(questions)}


GOOD_DECK = {
    "slides": [
        slide("Don't trust the trace alone", "The answer",
              bullets=["31.6% of correct answers had invalid traces [2609.38107v1]."],
              questions=[{"question": "Has this been tested in banking?",
                          "answer": "No. The research doesn't cover banking."}]),
        slide("Why it matters", minutes=2),
        slide("What to do next", minutes=3),
        slide("Sources", bullets=["2609.38107v1"], minutes=3),
    ],
    "watch_outs": ["Don't present the benchmark as a cost saving."],
}
DECK_TEXT = json.dumps(GOOD_DECK)


def brief_record():
    return {
        "query": "Can we trust AI reasoning?",
        "summary": SUMMARY,
        "sources": [{"paper_id": "2609.38107v1", "title": "Reasoning traces"},
                    {"paper_id": "2610.00001v1", "title": "Other paper"}],
        "citation_check": {"cited": ["2609.38107v1"]},
        "briefs": {"executive": {"brief": BRIEF}},
    }


# ---------- parser ----------

def test_parse_deck_reads_clean_json():
    deck = parse_deck(DECK_TEXT)
    assert len(deck["slides"]) == 4
    assert deck["slides"][0]["questions"][0]["question"] == "Has this been tested in banking?"
    assert deck["watch_outs"] == GOOD_DECK["watch_outs"]


def test_parse_deck_ignores_fences_and_prose():
    deck = parse_deck(f"Here are your slides:\n```json\n{DECK_TEXT}\n```\nGood luck!")
    assert [s["title"] for s in deck["slides"]][-1] == "Sources"


def test_parse_deck_coerces_and_caps_fields():
    messy = {"slides": [
        {"title": "**One**", "bullets": "- first\n- second", "notes": "n", "minutes": "1.5",
         "questions": ["Why?"]},
        {"title": "Two", "bullets": ["x" * 500] + ["b"] * 10, "notes": "n", "minutes": "soon"},
        {"title": "Three", "notes": "n"},
        "not a slide",
    ]}
    deck = parse_deck(json.dumps(messy))
    one, two, three = deck["slides"]
    assert one["title"] == "One"
    assert one["bullets"] == ["first", "second"]
    assert one["minutes"] == 1.5
    assert one["questions"] == [{"question": "Why?", "answer": ""}]
    assert len(two["bullets"]) == MAX_BULLETS and len(two["bullets"][0]) == BULLET_CHARS
    assert two["minutes"] == 0
    assert three["bullets"] == [] and deck["watch_outs"] == []


@pytest.mark.parametrize("reply", [
    "Sorry, I can't help with that.",
    "{not json}",
    json.dumps({"slides": "none"}),
    json.dumps({"slides": [slide("One"), slide("Two")]}),
    json.dumps({"slides": [slide("One", notes=""), slide("Two", notes=""), slide("Three", notes="")]}),
])
def test_parse_deck_rejects_unusable_replies(reply):
    with pytest.raises(ValueError):
        parse_deck(reply)


# ---------- prompt ----------

def test_prompt_has_audience_length_and_only_chosen_extras():
    r = brief_record()
    plain = build_present_prompt(r["query"], SUMMARY, BRIEF, r["sources"], "consultant", 5)
    assert PRESENT_AUDIENCES["consultant"] in plain
    assert "5 minutes, about 4 slides" in plain
    assert "No saved materials" in plain
    assert "2610.00001v1: Other paper" in plain

    extra = build_present_prompt(r["query"], SUMMARY, BRIEF, r["sources"], "executive", 20,
                                 [("Pilot plan: Claims triage", "- Measure today's process")])
    assert "### Pilot plan: Claims triage" in extra
    assert "about 11 slides" in extra
    assert PRESENT_AUDIENCES["executive"] in extra and PRESENT_AUDIENCES["consultant"] not in extra


def test_prompt_rejects_unknown_choices():
    with pytest.raises(ValueError):
        build_present_prompt("q", SUMMARY, BRIEF, [], "intern", 5)
    with pytest.raises(ValueError):
        build_present_prompt("q", SUMMARY, BRIEF, [], "executive", 7)


# ---------- checks ----------

def test_check_deck_passes_a_grounded_deck():
    checks = check_deck(parse_deck(DECK_TEXT), brief_record(), "", 10)
    assert checks["citations"]["ok"], checks
    assert checks["numbers"]["ok"], checks
    assert checks["structure"]["ok"], checks
    assert checks["structure"]["total_minutes"] == 10


def test_check_deck_flags_problems():
    deck = parse_deck(DECK_TEXT)
    deck["slides"][1]["bullets"] = ["It saves 30% of costs [9999.99999v1] [2610.00001v1]."]
    deck["slides"][2]["notes"] = ""
    deck["slides"] = deck["slides"][:3]  # no Sources slide

    checks = check_deck(deck, brief_record(), "", 20)

    assert checks["citations"]["not_retrieved"] == ["9999.99999"]
    assert checks["citations"]["not_in_summary"] == ["2610.00001"]
    assert "30%" in checks["numbers"]["ungrounded"]
    s = checks["structure"]
    assert not s["ok"] and s["missing_notes"] == [3] and not s["has_sources_slide"]
    assert not s["minutes_ok"]


def test_check_deck_accepts_numbers_from_extras():
    deck = parse_deck(DECK_TEXT)
    deck["slides"][1]["bullets"] = ["The pilot runs for 6 weeks with 250 claims."]
    assert check_deck(deck, brief_record(), "", 10)["numbers"]["ungrounded"] == ["250"]
    assert check_deck(deck, brief_record(), "Review 250 claims", 10)["numbers"]["ok"]


# ---------- routes ----------

@pytest.fixture
def present_setup(tmp_path):
    llm = CountingLLM([SUMMARY, BRIEF, DECK_TEXT, DECK_TEXT, DECK_TEXT])
    stores = {
        "adaptations": AdaptationStore(tmp_path / "adaptations"),
        "pilot_plans": PilotPlanStore(tmp_path / "plans"),
        "market_scans": MarketScanStore(tmp_path / "scans"),
        "presentations": PresentationStore(tmp_path / "decks"),
    }
    app = create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path / "briefs"), **stores)
    client = TestClient(app)
    brief_id = client.post("/api/ask", json={"question": "Can we trust AI reasoning?"}).json()["id"]
    return client, llm, brief_id


def test_generate_saves_lists_and_costs_one_call(present_setup):
    client, llm, brief_id = present_setup
    assert llm.calls == 2

    deck = client.post(f"/api/briefs/{brief_id}/presentations",
                       json={"audience": "consultant", "minutes": 10}).json()

    assert llm.calls == 3
    assert deck["audience"] == "consultant" and deck["minutes"] == 10
    assert len(deck["slides"]) == 4
    assert deck["brief_status"] == "draft"
    assert deck["checks"]["citations"]["ok"]

    listed = client.get(f"/api/briefs/{brief_id}/presentations").json()
    assert [d["id"] for d in listed["presentations"]] == [deck["id"]]
    assert listed["presentations"][0]["slides"] == 4

    assert client.get(f"/api/presentations/{deck['id']}").json()["slides"] == deck["slides"]
    assert llm.calls == 3


def test_edits_persist_and_are_rechecked_without_llm(present_setup):
    client, llm, brief_id = present_setup
    deck = client.post(f"/api/briefs/{brief_id}/presentations",
                       json={"audience": "executive", "minutes": 10}).json()
    calls = llm.calls

    slides = deck["slides"]
    slides[0]["bullets"] = ["Edited point that saves 45% [2609.38107v1]."]
    slides[1]["notes"] = ""
    saved = client.put(f"/api/presentations/{deck['id']}",
                       json={"slides": slides, "watch_outs": ["Be careful."]}).json()

    assert llm.calls == calls
    assert saved["checks"]["numbers"]["ungrounded"] == ["45%"]
    assert saved["checks"]["structure"]["missing_notes"] == [2]

    reopened = client.get(f"/api/presentations/{deck['id']}").json()
    assert reopened["slides"][0]["bullets"] == ["Edited point that saves 45% [2609.38107v1]."]
    assert reopened["watch_outs"] == ["Be careful."]


def test_delete(present_setup):
    client, _, brief_id = present_setup
    deck = client.post(f"/api/briefs/{brief_id}/presentations",
                       json={"audience": "executive", "minutes": 5}).json()
    assert client.delete(f"/api/presentations/{deck['id']}").status_code == 200
    assert client.get(f"/api/presentations/{deck['id']}").status_code == 404
    assert client.get(f"/api/briefs/{brief_id}/presentations").json()["presentations"] == []


def test_bad_requests(present_setup):
    client, llm, brief_id = present_setup
    url = f"/api/briefs/{brief_id}/presentations"
    assert client.post(url, json={"audience": "intern", "minutes": 10}).status_code == 400
    assert client.post(url, json={"audience": "executive", "minutes": 7}).status_code == 400
    assert client.post("/api/briefs/20260101-000000-abcdef/presentations",
                       json={"audience": "executive", "minutes": 10}).status_code == 404
    assert client.post(url, json={"audience": "executive", "minutes": 10,
                                  "pilot_plan_id": "20260101-000000-abcdef"}).status_code == 400
    assert llm.calls == 2


def test_saved_materials_are_offered_and_included(present_setup):
    client, llm, brief_id = present_setup
    adaptation = client.post(f"/api/briefs/{brief_id}/adaptations",
                             json={"industry": "Finance", "use_cases": ["Loan review"]}).json()
    plan = client.post(f"/api/adaptations/{adaptation['id']}/pilot-plans",
                       json={"title": "Loan pilot", "use_case": "Loan review",
                             "checklist": [{"text": "Sample 250 loan files"}]}).json()

    materials = client.get(f"/api/briefs/{brief_id}/presentations").json()["materials"]
    assert materials["adaptations"] == [{"id": adaptation["id"], "label": "Finance"}]
    assert materials["pilot_plans"] == [{"id": plan["id"], "label": "Loan pilot"}]

    prompts = []
    original = llm.generate
    llm.generate = lambda system, user: prompts.append(user) or original(system, user)

    deck = client.post(f"/api/briefs/{brief_id}/presentations",
                       json={"audience": "executive", "minutes": 10,
                             "adaptation_id": adaptation["id"], "pilot_plan_id": plan["id"]}).json()

    assert "Sample 250 loan files" in prompts[0] and "Loan review" in prompts[0]
    assert deck["extras"]["pilot_plan"] == {"id": plan["id"], "label": "Loan pilot"}


def test_extra_from_another_brief_is_refused(present_setup):
    client, llm, brief_id = present_setup
    llm.responses[:0] = [SUMMARY, BRIEF]
    other_id = client.post("/api/ask", json={"question": "Another question?"}).json()["id"]
    other = client.post(f"/api/briefs/{other_id}/adaptations", json={"industry": "Finance"}).json()
    calls = llm.calls

    response = client.post(f"/api/briefs/{brief_id}/presentations",
                           json={"audience": "executive", "minutes": 10, "adaptation_id": other["id"]})

    assert response.status_code == 400
    assert "different brief" in response.json()["detail"]
    assert llm.calls == calls


def test_audiences_change_the_prompt(present_setup):
    client, llm, brief_id = present_setup
    prompts = []
    original = llm.generate
    llm.generate = lambda system, user: prompts.append(user) or original(system, user)

    for audience in ("executive", "consultant"):
        client.post(f"/api/briefs/{brief_id}/presentations", json={"audience": audience, "minutes": 10})

    assert prompts[0] != prompts[1]
    assert PRESENT_AUDIENCES["consultant"] in prompts[1]


def test_options(tmp_path):
    app = create_app(FakeRetriever(make_papers()), CountingLLM([]), BriefStore(tmp_path / "briefs"))
    options = TestClient(app).get("/api/present/options").json()
    assert [a["id"] for a in options["audiences"]] == ["executive", "risk", "technical", "consultant"]
    assert [l["minutes"] for l in options["lengths"]] == [5, 10, 20]


# ---------- PowerPoint download ----------

def _read_pptx(data):
    from io import BytesIO

    from pptx import Presentation

    prs = Presentation(BytesIO(data))
    slides = []
    for s in prs.slides:
        text = [shape.text_frame.text for shape in s.shapes if shape.has_text_frame]
        notes = s.notes_slide.notes_text_frame.text if s.has_notes_slide else ""
        slides.append({"text": "\n".join(text), "notes": notes})
    return slides


def test_build_pptx_has_title_outline_and_watch_outs():
    from datetime import date

    from src.app.present_pptx import DRAFT_LINE, build_pptx

    deck = {**parse_deck(DECK_TEXT), "audience": "consultant", "minutes": 10}
    slides = _read_pptx(build_pptx(deck, "Can we trust AI reasoning?", "draft", today=date(2026, 11, 18)))

    assert len(slides) == 1 + 4 + 1  # title, outline slides, watch out for
    assert "Can we trust AI reasoning?" in slides[0]["text"]
    assert "Consultant Team · 10 minutes · November 18, 2026" in slides[0]["text"]
    assert DRAFT_LINE in slides[0]["text"]

    first = slides[1]
    assert "Don't trust the trace alone" in first["text"]
    assert "31.6% of correct answers had invalid traces [2609.38107v1]." in first["text"]
    assert "Say this." in first["notes"] and "Planned time: 2 min" in first["notes"]
    assert "Q: Has this been tested in banking?" in first["notes"]
    assert "A: No. The research doesn't cover banking." in first["notes"]

    assert "Watch out for" in slides[-1]["text"] and "Presenter only" in slides[-1]["notes"]


def test_build_pptx_approved_brief_has_no_draft_line():
    from src.app.present_pptx import DRAFT_LINE, build_pptx

    deck = {**parse_deck(DECK_TEXT), "audience": "executive", "minutes": 5}
    assert DRAFT_LINE not in _read_pptx(build_pptx(deck, "Q?", "approved"))[0]["text"]


def test_pptx_route_downloads_the_edited_deck_without_llm(present_setup):
    client, llm, brief_id = present_setup
    deck = client.post(f"/api/briefs/{brief_id}/presentations",
                       json={"audience": "executive", "minutes": 10}).json()
    slides = deck["slides"]
    slides[0]["bullets"] = ["An edited bullet."]
    client.put(f"/api/presentations/{deck['id']}", json={"slides": slides, "watch_outs": []})
    calls = llm.calls

    response = client.get(f"/api/presentations/{deck['id']}/pptx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.presentationml")
    assert response.headers["content-disposition"] == \
        'attachment; filename="can-we-trust-ai-reasoning-executive-10min.pptx"'
    pptx_slides = _read_pptx(response.content)
    assert "An edited bullet." in pptx_slides[1]["text"]
    assert len(pptx_slides) == 1 + 4  # no watch-outs slide once they're cleared
    assert llm.calls == calls

    assert client.get("/api/presentations/20260101-000000-abcdef/pptx").status_code == 404


def test_pptx_uses_the_brief_status_now(present_setup):
    from src.app.present_pptx import DRAFT_LINE

    client, _, brief_id = present_setup
    deck = client.post(f"/api/briefs/{brief_id}/presentations",
                       json={"audience": "executive", "minutes": 10}).json()
    assert DRAFT_LINE in _read_pptx(client.get(f"/api/presentations/{deck['id']}/pptx").content)[0]["text"]

    client.post(f"/api/briefs/{brief_id}/status", json={"status": "approved"})
    assert DRAFT_LINE not in _read_pptx(client.get(f"/api/presentations/{deck['id']}/pptx").content)[0]["text"]
