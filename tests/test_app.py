import pytest
from fastapi.testclient import TestClient

from src.app.checks import evidence_level, run_checks, template_check
from src.app.server import create_app
from src.app.store import BriefStore

from tests.test_pipeline import FakeRetriever, make_papers

SUMMARY = (
    "Research Objective:\nCheck reasoning traces. [2609.38107v1]\n\n"
    "Key Findings:\n31.6% of correct answers had invalid traces. [2609.38107v1]"
)

BRIEF = """## Bottom Line
Not on its own. [2609.38107v1]

## Why It Matters
- Explanations can mislead. [2609.38107v1]

## What To Do
- Verify answers independently.

## Evidence Strength
Medium. One paper, small models, lab benchmark. [2609.38107v1]

## Caveat
- Validate before relying on it.

## Sources
2609.38107v1
"""


class CountingLLM:
    provider = "groq"
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_finish_reason = "stop"

    def generate(self, system_prompt, user_prompt):
        self.calls += 1
        return self.responses.pop(0)


@pytest.fixture
def setup(tmp_path):
    llm = CountingLLM([SUMMARY, BRIEF, BRIEF.replace("Not on its own.", "Risk view.")])
    store = BriefStore(tmp_path / "briefs")
    app = create_app(FakeRetriever(make_papers()), llm, store,
                     corpus={"papers": 2, "first_date": "2026-09-29", "last_date": "2026-10-11"},
                     examples=["Q?"])
    return TestClient(app), llm


def test_ask_saves_and_lists_the_brief(setup):
    client, llm = setup

    record = client.post("/api/ask", json={"question": "Can we trust AI reasoning?"}).json()

    assert llm.calls == 2
    assert record["status"] == "draft"
    assert record["briefs"]["executive"]["brief"] == BRIEF
    assert record["briefs"]["executive"]["checks"]["template"]["ok"]
    assert record["briefs"]["executive"]["checks"]["citations"]["ok"]

    listed = client.get("/api/briefs").json()
    assert [b["id"] for b in listed] == [record["id"]]

    # reopening costs no LLM calls
    assert client.get(f"/api/briefs/{record['id']}").json()["summary"] == SUMMARY
    assert llm.calls == 2


def test_status_update_is_saved(setup):
    client, _ = setup
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]

    client.post(f"/api/briefs/{brief_id}/status", json={"status": "changes", "note": " too vague "})

    record = client.get(f"/api/briefs/{brief_id}").json()
    assert record["status"] == "changes"
    assert record["note"] == "too vague"
    assert client.post(f"/api/briefs/{brief_id}/status", json={"status": "done"}).status_code == 400


def test_rewrite_uses_one_call_and_keeps_the_first_brief(setup):
    client, llm = setup
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]
    client.post(f"/api/briefs/{brief_id}/status", json={"status": "approved"})

    record = client.post(f"/api/briefs/{brief_id}/rewrite", json={"audience": "risk"}).json()

    assert llm.calls == 3
    assert record["briefs"]["executive"]["brief"] == BRIEF
    assert record["briefs"]["risk"]["brief"].startswith("## Bottom Line\nRisk view.")
    assert record["audience"] == "risk"
    assert record["status"] == "draft"


def test_bad_requests(setup):
    client, llm = setup

    assert client.post("/api/ask", json={"question": "   "}).status_code == 400
    assert client.post("/api/ask", json={"question": "Q?", "audience": "intern"}).status_code == 400
    assert client.post("/api/ask", json={"question": "Q?", "top_k": 10}).status_code == 400
    assert client.get("/api/briefs/does-not-exist").status_code == 404
    assert client.get("/api/briefs/..%2F..%2Fetc").status_code == 404
    assert llm.calls == 0


def test_llm_errors_become_messages(tmp_path):
    class DailyLimitLLM(CountingLLM):
        def generate(self, system_prompt, user_prompt):
            raise RuntimeError("The daily groq limit for this API key is used up.")

    app = create_app(FakeRetriever(make_papers()), DailyLimitLLM([]), BriefStore(tmp_path))
    response = TestClient(app).post("/api/ask", json={"question": "Q?"})

    assert response.status_code == 503
    assert "daily groq limit" in response.json()["detail"]


def test_index_and_info_are_served(setup):
    client, _ = setup

    assert "Research Insight Agent" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
    info = client.get("/api/info").json()
    assert info["corpus"]["papers"] == 2
    assert info["model"] == "fake-model"


# ---------- checks ----------

def test_template_check():
    assert template_check(BRIEF)["ok"]
    assert not template_check(BRIEF.replace("## Caveat", "## Caveats"))["ok"]
    assert not template_check(BRIEF + " word" * 200)["ok"]


def test_evidence_level():
    assert evidence_level(BRIEF) == {"level": "Medium", "reason": "One paper, small models, lab benchmark."}
    assert evidence_level("## Evidence Strength\n**High.** Many papers.")["level"] == "High"
    assert evidence_level("## Bottom Line\nNo rating.")["level"] is None


def test_citation_check_flags_problems():
    result = {"citation_check": {"cited_not_retrieved": ["2609.99999"]}, "truncated": False}
    insight = {"brief": BRIEF, "truncated": True, "citation_check": {"cited_not_in_summary": []}}

    checks = run_checks(result, insight)

    assert not checks["citations"]["ok"]
    assert checks["brief_truncated"]
