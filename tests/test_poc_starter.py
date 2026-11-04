import pytest
from fastapi.testclient import TestClient

from src.app.server import create_app
from src.app.store import BriefStore
from src.translation.poc_prompts import (
    MAX_STEPS,
    build_poc_checklist_prompt,
    parse_checklist,
)

from tests.test_app import BRIEF, SUMMARY, CountingLLM
from tests.test_pipeline import FakeRetriever, make_papers

REPLY = """Here is a pilot checklist:

- Get read access to the claims inbox
- **Measure** how long a manual review takes today
- Run the agent on 20 past cases
- Record every correction a reviewer makes
- Decide whether to expand, change or stop
"""

ANSWERS = {
    "Who would run the pilot?": "Two analysts",
    "How long should the pilot run?": "8 weeks",
    "What worries you most?": "",
}

REQUEST = {
    "industry": "Healthcare",
    "use_case": "Route insurance paperwork before staff review",
    "answers": ANSWERS,
}


class RecordingLLM(CountingLLM):
    """CountingLLM that also keeps the prompts it was sent."""

    def __init__(self, responses):
        super().__init__(responses)
        self.prompts = []

    def generate(self, system_prompt, user_prompt):
        self.prompts.append((system_prompt, user_prompt))
        return super().generate(system_prompt, user_prompt)


@pytest.fixture
def setup(tmp_path):
    llm = RecordingLLM([SUMMARY, BRIEF, REPLY, REPLY])
    store = BriefStore(tmp_path / "briefs")
    client = TestClient(create_app(FakeRetriever(make_papers()), llm, store))
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]
    return client, llm, brief_id, store


# ---------- parsing the model's reply ----------


def test_parse_checklist_keeps_only_list_items():
    steps = parse_checklist(REPLY)

    assert [s["text"] for s in steps] == [
        "Get read access to the claims inbox",
        "Measure how long a manual review takes today",   # ** removed
        "Run the agent on 20 past cases",
        "Record every correction a reviewer makes",
        "Decide whether to expand, change or stop",
    ]
    assert all(s["done"] is False for s in steps)


def test_parse_checklist_accepts_numbers_and_checkboxes():
    text = "1. First step\n2) Second step\n* [ ] Third step\n- [x] Fourth step\n\n## A heading"

    assert [s["text"] for s in parse_checklist(text)] == [
        "First step", "Second step", "Third step", "Fourth step",
    ]


def test_parse_checklist_caps_the_number_of_steps():
    text = "\n".join(f"- Step {n}" for n in range(30))

    assert len(parse_checklist(text)) == MAX_STEPS


def test_parse_checklist_rejects_replies_without_steps():
    with pytest.raises(ValueError):
        parse_checklist("I can't help with that.")

    with pytest.raises(ValueError):
        parse_checklist("- Only one\n- Or two")


# ---------- the prompt ----------


def test_prompt_has_the_use_case_answers_and_summary():
    prompt = build_poc_checklist_prompt(SUMMARY, "Healthcare", "Route paperwork", ANSWERS)

    assert prompt.startswith("Target industry: Healthcare\nUse case: Route paperwork\n")
    assert "- Who would run the pilot? Two analysts" in prompt
    assert "- What worries you most? Not answered" in prompt
    assert prompt.endswith(f"Saved research summary:\n{SUMMARY}")


# ---------- the route ----------


def test_pilot_checklist_uses_one_llm_call_and_saves_nothing(setup, tmp_path):
    client, llm, brief_id, _ = setup

    response = client.post(f"/api/briefs/{brief_id}/pilot-checklist", json=REQUEST)

    assert response.status_code == 200
    assert len(response.json()["checklist"]) == 5
    assert llm.calls == 3  # the question (2 calls) + this checklist (1 call)

    system_prompt, user_prompt = llm.prompts[-1]
    assert "Never say the research tested this pilot" in " ".join(system_prompt.split())  # ignores line breaks
    assert "Use case: Route insurance paperwork before staff review" in user_prompt
    assert "Key Findings:\n31.6% of correct answers" in user_prompt

    # Nothing is saved until the page creates a pilot plan
    assert list((tmp_path / "ui_pilot_plans").glob("*.json")) == []


def test_pilot_checklist_bad_requests(setup):
    client, llm, brief_id, store = setup
    path = f"/api/briefs/{brief_id}/pilot-checklist"

    assert client.post(path, json={**REQUEST, "use_case": "   "}).status_code == 400
    assert client.post(path, json={**REQUEST, "industry": ""}).status_code == 400
    assert client.post(path, json={**REQUEST, "use_case": "x" * 301}).status_code == 400
    assert client.post(path, json={**REQUEST, "answers": {"Q": "x" * 301}}).status_code == 400
    assert client.post(path, json={**REQUEST, "answers": {str(n): "a" for n in range(11)}}).status_code == 400
    assert client.post("/api/briefs/does-not-exist/pilot-checklist", json=REQUEST).status_code == 404
    assert llm.calls == 2  # none of these reached the model

    # A brief with no research summary has nothing to build a pilot from
    store.save({"id": "20260101-000000-abcdef", "query": "Q?", "summary": "", "sources": [], "briefs": {}})
    empty = client.post("/api/briefs/20260101-000000-abcdef/pilot-checklist", json=REQUEST)
    assert empty.status_code == 400
    assert llm.calls == 2


def test_unusable_reply_becomes_a_message(tmp_path):
    llm = RecordingLLM([SUMMARY, BRIEF, "Sorry, no."])
    client = TestClient(create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path)))
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]

    response = client.post(f"/api/briefs/{brief_id}/pilot-checklist", json=REQUEST)

    assert response.status_code == 400
    assert "usable checklist" in response.json()["detail"]


def test_llm_errors_become_messages(tmp_path):
    class DailyLimitLLM(RecordingLLM):
        def generate(self, system_prompt, user_prompt):
            if self.calls >= 2:
                raise RuntimeError("The daily groq limit for this API key is used up.")
            return super().generate(system_prompt, user_prompt)

    llm = DailyLimitLLM([SUMMARY, BRIEF])
    client = TestClient(create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path)))
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]

    response = client.post(f"/api/briefs/{brief_id}/pilot-checklist", json=REQUEST)

    assert response.status_code == 503
    assert "daily groq limit" in response.json()["detail"]


def test_the_steps_the_page_takes_from_checklist_to_saved_plan(setup):
    """The same calls poc.js makes: generate, save an adaptation and plan, tick a box."""
    client, llm, brief_id, _ = setup

    checklist = client.post(f"/api/briefs/{brief_id}/pilot-checklist", json=REQUEST).json()["checklist"]

    adaptation = client.post(f"/api/briefs/{brief_id}/adaptations", json={
        "industry": "Healthcare", "use_cases": [REQUEST["use_case"]], "created_by": "Lakshmee",
    }).json()

    plan = client.post(f"/api/adaptations/{adaptation['id']}/pilot-plans", json={
        "title": "Pilot: " + REQUEST["use_case"],
        "use_case": REQUEST["use_case"],
        "answers": ANSWERS,
        "checklist": checklist,
        "created_by": "Lakshmee",
    }).json()

    assert [i["text"] for i in plan["checklist"]] == [i["text"] for i in checklist]
    assert plan["answers"]["Who would run the pilot?"] == "Two analysts"

    # Ticking a box sends just the checklist
    checklist[0]["done"] = True
    saved = client.put(f"/api/pilot-plans/{plan['id']}", json={"checklist": checklist}).json()
    assert saved["checklist"][0]["done"] is True
    assert saved["use_case"] == REQUEST["use_case"]  # fields left out are kept

    # The saved plans for the brief are what the page lists
    listed = client.get("/api/pilot-plans", params={"brief_id": brief_id}).json()
    assert [p["id"] for p in listed] == [plan["id"]]
    assert llm.calls == 3  # only the checklist cost an LLM call
