import pytest
from fastapi.testclient import TestClient

from src.app.server import create_app
from src.app.store import AdaptationStore, BriefStore, CommentStore, PilotPlanStore

from tests.test_app import BRIEF, SUMMARY, CountingLLM
from tests.test_pipeline import FakeRetriever, make_papers

ADAPTATION = {
    "industry": "Healthcare",
    "use_cases": ["Flag unreliable AI explanations in clinical triage", "  "],
    "constraints": ["HIPAA", {"name": "Budget", "detail": "Pilot under $50k"}],
    "considerations": ["Clinician sign-off before rollout"],
    "created_by": "Chythra",
}

PILOT = {
    "title": "Triage pilot",
    "use_case": "Flag unreliable AI explanations in clinical triage",
    "answers": {"Team size?": "4", "Timeline?": "8 weeks"},
    "checklist": [{"text": "Pick 50 test cases"}, {"text": "Get clinician reviewer", "done": True}],
    "created_by": "Lakshmee",
}


@pytest.fixture
def setup(tmp_path):
    llm = CountingLLM([SUMMARY, BRIEF])
    app = create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path / "briefs"))
    client = TestClient(app)
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]
    return client, llm, brief_id, tmp_path


def test_adaptation_is_saved_and_listed(setup):
    client, llm, brief_id, tmp_path = setup

    created = client.post(f"/api/briefs/{brief_id}/adaptations", json=ADAPTATION).json()
    assert created["brief_id"] == brief_id
    assert created["industry"] == "Healthcare"
    assert created["use_cases"] == ["Flag unreliable AI explanations in clinical triage"]  # blank dropped
    assert created["constraints"][1] == {"name": "Budget", "detail": "Pilot under $50k"}
    assert created["pilot_plans"] == [] and created["comments"] == []

    # Saved as a file next to the briefs, and readable again
    assert (tmp_path / "ui_adaptations" / f"{created['id']}.json").exists()
    assert client.get(f"/api/adaptations/{created['id']}").json()["industry"] == "Healthcare"

    assert [a["id"] for a in client.get(f"/api/briefs/{brief_id}/adaptations").json()] == [created["id"]]
    assert len(client.get("/api/adaptations", params={"industry": "healthcare"}).json()) == 1
    assert client.get("/api/adaptations", params={"industry": "Finance"}).json() == []
    assert llm.calls == 2  # storage never calls the LLM


def test_adaptation_update_keeps_fields_left_out(setup):
    client, _, brief_id, _ = setup
    adaptation_id = client.post(f"/api/briefs/{brief_id}/adaptations", json=ADAPTATION).json()["id"]

    updated = client.put(f"/api/adaptations/{adaptation_id}",
                         json={"considerations": ["Start with one hospital"]}).json()
    assert updated["considerations"] == ["Start with one hospital"]
    assert updated["industry"] == "Healthcare"
    assert updated["created_by"] == "Chythra"


def test_adaptation_bad_requests(setup):
    client, _, brief_id, _ = setup
    assert client.post(f"/api/briefs/{brief_id}/adaptations", json={"industry": " "}).status_code == 400
    assert client.post(f"/api/briefs/{brief_id}/adaptations", json={"industry": "x" * 500}).status_code == 400
    assert client.post(f"/api/briefs/{brief_id}/adaptations",
                       json={"industry": "Retail", "use_cases": ["u"] * 51}).status_code == 400
    assert client.post("/api/briefs/20260101-000000-abcdef/adaptations", json=ADAPTATION).status_code == 404
    assert client.get("/api/adaptations/nope").status_code == 404
    assert client.get("/api/adaptations/20260101-000000-abcdef").status_code == 404


def test_pilot_plan_saved_edited_and_linked(setup):
    client, _, brief_id, _ = setup
    adaptation_id = client.post(f"/api/briefs/{brief_id}/adaptations", json=ADAPTATION).json()["id"]

    plan = client.post(f"/api/adaptations/{adaptation_id}/pilot-plans", json=PILOT).json()
    assert plan["adaptation_id"] == adaptation_id
    assert plan["brief_id"] == brief_id
    assert plan["industry"] == "Healthcare"
    assert plan["checklist"] == [{"text": "Pick 50 test cases", "done": False},
                                 {"text": "Get clinician reviewer", "done": True}]

    # Tick a box: send only the checklist, everything else stays
    ticked = client.put(f"/api/pilot-plans/{plan['id']}", json={"checklist": [
        {"text": "Pick 50 test cases", "done": True},
        {"text": "Get clinician reviewer", "done": True},
        {"text": "Book kickoff"},
    ]}).json()
    assert [i["done"] for i in ticked["checklist"]] == [True, True, False]
    assert ticked["answers"] == PILOT["answers"]

    assert [p["id"] for p in client.get(f"/api/adaptations/{adaptation_id}").json()["pilot_plans"]] == [plan["id"]]
    assert len(client.get("/api/pilot-plans", params={"brief_id": brief_id}).json()) == 1


def test_pilot_plan_bad_requests(setup):
    client, _, brief_id, _ = setup
    adaptation_id = client.post(f"/api/briefs/{brief_id}/adaptations", json=ADAPTATION).json()["id"]
    assert client.post(f"/api/adaptations/{adaptation_id}/pilot-plans", json={"title": "No use case"}).status_code == 400
    assert client.post("/api/adaptations/20260101-000000-abcdef/pilot-plans", json=PILOT).status_code == 404
    assert client.get("/api/pilot-plans/20260101-000000-abcdef").status_code == 404


def test_comments_on_each_kind_of_item(setup):
    client, _, brief_id, _ = setup
    adaptation_id = client.post(f"/api/briefs/{brief_id}/adaptations", json=ADAPTATION).json()["id"]
    plan_id = client.post(f"/api/adaptations/{adaptation_id}/pilot-plans", json=PILOT).json()["id"]

    for target_type, target_id in (("brief", brief_id), ("adaptation", adaptation_id), ("pilot_plan", plan_id)):
        first = client.post("/api/comments", json={
            "target_type": target_type, "target_id": target_id, "author": "Olivia", "text": " First "}).json()
        client.post("/api/comments", json={
            "target_type": target_type, "target_id": target_id, "author": "Grace", "text": "Second"})
        assert first["text"] == "First" and first["author"] == "Olivia" and first["created_at"]

        thread = client.get("/api/comments", params={"target_type": target_type, "target_id": target_id}).json()
        assert [c["text"] for c in thread] == ["First", "Second"]  # oldest first

    assert len(client.get(f"/api/adaptations/{adaptation_id}").json()["comments"]) == 2
    assert len(client.get(f"/api/pilot-plans/{plan_id}").json()["comments"]) == 2

    assert client.delete(f"/api/comments/{first['id']}").json() == {"deleted": first["id"]}
    assert len(client.get(f"/api/pilot-plans/{plan_id}").json()["comments"]) == 1


def test_comment_bad_requests(setup):
    client, _, brief_id, _ = setup
    ok = {"target_type": "brief", "target_id": brief_id, "author": "Olivia", "text": "Hi"}
    assert client.post("/api/comments", json={**ok, "target_type": "project"}).status_code == 400
    assert client.post("/api/comments", json={**ok, "author": " "}).status_code == 400
    assert client.post("/api/comments", json={**ok, "text": ""}).status_code == 400
    assert client.post("/api/comments", json={**ok, "text": "x" * 5000}).status_code == 400
    assert client.post("/api/comments", json={**ok, "target_id": "20260101-000000-abcdef"}).status_code == 404
    assert client.get("/api/comments", params={"target_type": "x", "target_id": brief_id}).status_code == 400
    assert client.delete("/api/comments/20260101-000000-abcdef").status_code == 404


def test_deleting_an_adaptation_removes_its_plans_and_comments(setup):
    client, _, brief_id, tmp_path = setup
    adaptation_id = client.post(f"/api/briefs/{brief_id}/adaptations", json=ADAPTATION).json()["id"]
    plan_id = client.post(f"/api/adaptations/{adaptation_id}/pilot-plans", json=PILOT).json()["id"]
    for target_type, target_id in (("adaptation", adaptation_id), ("pilot_plan", plan_id), ("brief", brief_id)):
        client.post("/api/comments", json={
            "target_type": target_type, "target_id": target_id, "author": "Olivia", "text": "Note"})

    assert client.delete(f"/api/adaptations/{adaptation_id}").status_code == 200
    assert client.get(f"/api/adaptations/{adaptation_id}").status_code == 404
    assert client.get(f"/api/pilot-plans/{plan_id}").status_code == 404
    remaining = CommentStore(tmp_path / "ui_comments").list()
    assert [c["target_type"] for c in remaining] == ["brief"]  # the brief and its comments stay
    assert client.get(f"/api/briefs/{brief_id}").status_code == 200


def test_stores_work_without_the_app(tmp_path):
    adaptations = AdaptationStore(tmp_path / "a")
    record = adaptations.save({"id": adaptations.new_id(), "brief_id": "b1", "industry": "Finance",
                               "created_at": "2026-11-01T00:00:00+00:00"})
    assert adaptations.load(record["id"])["industry"] == "Finance"
    assert adaptations.list(brief_id="b1")[0]["id"] == record["id"]
    adaptations.delete(record["id"])
    with pytest.raises(KeyError):
        adaptations.load(record["id"])
    with pytest.raises(KeyError):
        adaptations.delete("../../etc/passwd")  # ids outside the folder are refused

    plans = PilotPlanStore(tmp_path / "p")
    assert plans.list() == []
