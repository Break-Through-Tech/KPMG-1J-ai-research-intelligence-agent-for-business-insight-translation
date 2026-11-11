from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.app.server import create_app
from src.app.store import BriefStore, MarketScanStore, ProjectStore
from src.market.edgar import EdgarClient, EdgarError, html_to_text, parse_filing
from src.market.scan import (
    check_scan,
    clean_phrases,
    collect_filings,
    excerpts,
    gather,
    in_industry,
    suggest_phrases,
    useful_document,
)
from src.translation.market_prompts import MARKET_SECTIONS, build_market_scan_prompt

from tests.test_app import BRIEF, SUMMARY, CountingLLM
from tests.test_pipeline import FakeRetriever, make_papers

TODAY = date(2026, 11, 10)


def filing(n, company, sics=("7372",), document_type=None, form="10-K"):
    return {
        "company": company, "ticker": "", "cik": str(n), "form": form,
        "document_type": document_type or form, "description": "", "filed": f"2026-10-{10 + n:02d}",
        "period": "", "items": [], "sics": list(sics), "adsh": f"000-{n}",
        "url": f"https://www.sec.gov/doc{n}.htm", "index_url": "", "score": 1.0,
    }


class FakeEdgar:
    """Answers like EdgarClient, from fixed data, and records the queries."""

    def __init__(self, filings, text=None, recent=40, earlier=20):
        self.filings = filings
        self.text = text or ("Our business grew. We sell analytics tools. We now use large language models "
                             "to review contracts, which cut review time by 30%. Customers renewed. Costs fell.")
        self.recent, self.earlier = recent, earlier
        self.queries = []

    def search(self, query, since, until, forms=None, page=0):
        self.queries.append(query)
        return {"total": len(self.filings), "filings": self.filings if page == 0 else []}

    def count(self, query, since, until, forms=None):
        return self.recent if until.year == TODAY.year else self.earlier

    def document_text(self, f):
        return self.text


MARKET_TEXT = """## Market Snapshot
Software companies report using large language models to review contracts [F1].

## Who's Moving
- Acme Corp says review time fell by 30% [F1].

## Demand Signals
- Mentions rose from 20 to 40 filings, +100% [D1].

## Research vs Market
- Research flags invalid reasoning traces [2609.38107v1], which filings don't mention.

## Growth Opportunities
- Opportunity (interpretation): AI assurance reviews. For: our firm. Why now: [D1] [F1]. Confidence: Medium.

## Risks & Headwinds
- Reasoning may not be faithful [2609.38107v1].

## Watch List
- Watch 8-K announcements.
"""


# ---------- scan helpers ----------

def test_suggest_phrases_uses_filing_wording_question_first():
    record = {"query": "How consistent is gender bias across AI language models?",
              "summary": "Agents were tested.", "sources": [{"title": "Bias in LLMs"}]}
    assert suggest_phrases(record) == ["algorithmic bias", "large language models", "agentic AI"]


def test_suggest_phrases_falls_back_to_general_terms():
    assert suggest_phrases({"query": "What changed this week?", "summary": "", "sources": []}) == [
        "generative AI", "artificial intelligence"]


def test_clean_phrases_validates():
    assert clean_phrases([" agentic  AI ", "Agentic AI", ""]) == ["agentic AI"]
    with pytest.raises(ValueError):
        clean_phrases([])
    with pytest.raises(ValueError):
        clean_phrases(['" OR 1=1 --'])
    with pytest.raises(ValueError):
        clean_phrases(["a b", "c d", "e f", "g h", "i j"])


def test_industry_and_document_filters():
    bank = filing(1, "Bank", sics=["6022"])
    assert in_industry(bank, "Finance") and not in_industry(bank, "Healthcare")
    assert in_industry(bank, "Cross-industry") and in_industry(bank, "Government & Public Services")
    assert not in_industry(filing(2, "SPAC", sics=["6770"]), "Finance")
    assert useful_document(filing(3, "A", document_type="EX-99.1", form="8-K"))
    assert not useful_document(filing(4, "B", document_type="EX-2.1", form="8-K"))


def test_collect_filings_one_per_company_taking_turns():
    filings = [filing(1, "A"), filing(1, "A again"), filing(2, "B"), filing(3, "C", document_type="EX-10.1")]
    chosen = collect_filings(FakeEdgar(filings), ["large language models", "agentic AI"],
                             "Cross-industry", TODAY, TODAY)
    assert [(f["company"], f["phrase"]) for f in chosen] == [
        ("A", "large language models"), ("B", "agentic AI")]


def test_government_adds_a_search_word():
    edgar = FakeEdgar([filing(1, "A")])
    collect_filings(edgar, ["chatbot"], "Government & Public Services", TODAY, TODAY)
    assert edgar.queries == ['"chatbot" government']


def test_excerpts_keep_two_sentences_each_side_and_skip_repeats():
    text = ("ea001ex99-1.htm Large language model launch. One. Two. Three. We built a large language model. "
            "Four. Five. Six.")
    # the second mention is inside the first excerpt's reach, so it isn't quoted again
    assert excerpts(text, "large language model") == ["Large language model launch. One. Two."]

    far = ("Start here. Our large language model shipped. Alpha one. Bravo two. Charlie three. "
           + "Filler text. " * 100 + "Delta four. Echo five. Large language models cut costs. "
           "Fox six. Golf seven. Hotel eight.")
    found = excerpts(far, "large language model")
    assert found == ["Start here. Our large language model shipped. Alpha one. Bravo two.",
                     "Delta four. Echo five. Large language models cut costs. Fox six. Golf seven."]


def test_gather_numbers_sources_and_counts():
    gathered = gather(FakeEdgar([filing(1, "Acme Corp"), filing(2, "Beta")]),
                      ["large language models"], "Cross-industry", 90, today=TODAY)
    assert [f["id"] for f in gathered["filings"]] == ["F1", "F2"]
    assert gathered["signals"] == [{"id": "D1", "phrase": "large language models",
                                    "recent": 40, "year_earlier": 20, "change": 100}]
    assert gathered["since"] == "2026-08-12" and gathered["until"] == "2026-11-10"


def test_check_scan_flags_unknown_sources_and_untraced_numbers():
    gathered = gather(FakeEdgar([filing(1, "Acme Corp")]), ["large language models"],
                      "Cross-industry", 90, today=TODAY)
    record = {"summary": SUMMARY, "sources": [{"paper_id": "2609.38107v1"}],
              "citation_check": {"cited": ["2609.38107"]}}

    good = check_scan(MARKET_TEXT, gathered, record)
    assert good["citations"]["ok"] and good["numbers"]["ok"] and good["template"]["ok"]
    assert good["sources"]["thin"]

    assert good["targets"]["ok"]
    named = check_scan(MARKET_TEXT.replace("For: our firm.", "For: Acme Corp."), gathered, record)
    assert named["targets"]["named"] == ["Acme Corp"]

    bad = check_scan(MARKET_TEXT + "\n- Market worth $45 billion [F7].", gathered, record)
    assert bad["citations"]["unknown_sources"] == ["F7"]
    assert "45" in bad["numbers"]["ungrounded"]


def test_prompt_has_sources_and_lens():
    gathered = gather(FakeEdgar([filing(1, "Acme Corp", sics=["6022"])]), ["large language models"],
                      "Finance", 90, today=TODAY)
    prompt = build_market_scan_prompt("Q?", SUMMARY, gathered, "Finance", "firm")
    assert "[F1] Acme Corp. 10-K, filed" in prompt
    assert "[D1] \"large language models\": 40 now, 20 a year earlier (+100%)" in prompt
    assert "advisory, risk and assurance" in prompt


# ---------- EDGAR client ----------

def test_parse_filing_and_html_to_text():
    hit = {"_id": "0001289419-26-000044:morn.htm", "_score": 3.0, "_source": {
        "ciks": ["0001289419"], "display_names": ["Morningstar, Inc.  (MORN)  (CIK 0001289419)"],
        "form": "8-K", "file_type": "EX-99.1", "file_date": "2026-08-25", "sics": ["6282"], "items": ["7.01"]}}
    f = parse_filing(hit)
    assert (f["company"], f["ticker"], f["form"], f["document_type"]) == ("Morningstar, Inc.", "MORN", "8-K", "EX-99.1")
    assert f["url"] == "https://www.sec.gov/Archives/edgar/data/1289419/000128941926000044/morn.htm"

    raw = "<html><ix:header>hidden 123</ix:header><p>We use&nbsp;AI.</p><script>x()</script><div>Next</div></html>"
    assert html_to_text(raw) == "We use AI.\nNext"


class FakeResponse:
    def __init__(self, status=200):
        self.status_code = status

    def json(self):
        return {"hits": {"total": {"value": 0}, "hits": []}}


class FakeSession:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        self.calls.append((url, params, headers))
        return FakeResponse(self.status)


def test_client_sends_user_agent_and_rate_limits():
    session = FakeSession()
    waits = []
    edgar = EdgarClient("Team you@school.edu", session=session, sleep=waits.append, clock=lambda: 0.0)
    edgar.search('"chatbot"', TODAY, TODAY)
    edgar.search('"chatbot"', TODAY, TODAY, page=1)
    assert session.calls[0][2]["User-Agent"] == "Team you@school.edu"
    assert session.calls[1][1]["from"] == 100
    assert waits == [pytest.approx(0.15)]


def test_client_errors_are_explained():
    with pytest.raises(ValueError):
        EdgarClient("  ")
    edgar = EdgarClient("Team you@school.edu", session=FakeSession(403), sleep=lambda s: None)
    with pytest.raises(EdgarError, match="SEC_USER_AGENT"):
        edgar.count('"chatbot"', TODAY, TODAY)


# ---------- routes ----------

@pytest.fixture
def market_setup(tmp_path):
    llm = CountingLLM([SUMMARY, BRIEF, MARKET_TEXT, MARKET_TEXT])
    edgar = FakeEdgar([filing(1, "Acme Corp"), filing(2, "Beta"), filing(3, "Gamma")])
    projects = ProjectStore(tmp_path / "projects")
    app = create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path / "briefs"),
                     projects=projects, market_scans=MarketScanStore(tmp_path / "scans"), edgar=edgar)
    client = TestClient(app)
    brief_id = client.post("/api/ask", json={"question": "Can we trust LLM reasoning?"}).json()["id"]
    return client, llm, brief_id


def run_scan(client, brief_id, **overrides):
    body = {"phrases": ["large language models"], "industry": "Cross-industry", "lens": "both",
            "window_days": 90, **overrides}
    return client.post(f"/api/briefs/{brief_id}/market-scans", json=body)


def test_market_scan_runs_saves_and_lists(market_setup):
    client, llm, brief_id = market_setup

    assert client.get("/api/market/options").json()["configured"] is True
    assert "large language models" in client.get(f"/api/briefs/{brief_id}/market-phrases").json()["phrases"]

    response = run_scan(client, brief_id)
    assert response.status_code == 200
    scan = response.json()
    assert llm.calls == 3   # summary, brief, market scan
    assert scan["status"] == "draft" and scan["checks"]["citations"]["ok"]
    assert [f["id"] for f in scan["sources"]["filings"]] == ["F1", "F2", "F3"]

    assert [s["id"] for s in client.get(f"/api/briefs/{brief_id}/market-scans").json()] == [scan["id"]]
    assert client.get(f"/api/market-scans/{scan['id']}").json()["scan"] == MARKET_TEXT
    assert client.get("/api/briefs").json()[0]["market_scans"] == 1


def test_market_scan_review_and_delete(market_setup):
    client, _, brief_id = market_setup
    scan_id = run_scan(client, brief_id).json()["id"]

    reviewed = client.post(f"/api/market-scans/{scan_id}/status", json={"status": "changes", "note": " more 8-Ks "}).json()
    assert reviewed["status"] == "changes" and reviewed["note"] == "more 8-Ks"
    assert client.post(f"/api/market-scans/{scan_id}/status", json={"status": "done"}).status_code == 400

    assert client.delete(f"/api/market-scans/{scan_id}").status_code == 200
    assert client.get(f"/api/market-scans/{scan_id}").status_code == 404


def test_market_scans_for_a_project(market_setup):
    client, _, brief_id = market_setup
    project = client.post("/api/projects", json={"name": "Bank engagement"}).json()
    client.post(f"/api/projects/{project['id']}/briefs", json={"brief_id": brief_id})
    scan_id = run_scan(client, brief_id).json()["id"]

    assert [s["id"] for s in client.get(f"/api/market-scans?project_id={project['id']}").json()] == [scan_id]


def test_market_scan_bad_requests(market_setup):
    client, llm, brief_id = market_setup
    assert run_scan(client, brief_id, industry="Mining").status_code == 400
    assert run_scan(client, brief_id, lens="other").status_code == 400
    assert run_scan(client, brief_id, window_days=7).status_code == 400
    assert run_scan(client, brief_id, phrases=[]).status_code == 400
    assert run_scan(client, "20260101-000000-abcdef").status_code == 404
    assert llm.calls == 2   # no LLM call for any of them


def test_market_scan_without_edgar_or_filings(tmp_path):
    llm = CountingLLM([SUMMARY, BRIEF])
    app = create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path / "briefs"),
                     market_scans=MarketScanStore(tmp_path / "scans"), edgar=None)
    client = TestClient(app)
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]

    options = client.get("/api/market/options").json()
    assert options["configured"] is False and "SEC_USER_AGENT" in options["setup"]
    assert run_scan(client, brief_id).status_code == 503

    app = create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path / "briefs"),
                     market_scans=MarketScanStore(tmp_path / "scans"), edgar=FakeEdgar([]))
    response = run_scan(TestClient(app), brief_id)
    assert response.status_code == 404 and "No filings" in response.json()["detail"]


def test_edgar_failure_is_a_502(market_setup, tmp_path):
    class DownEdgar(FakeEdgar):
        def count(self, *args, **kwargs):
            raise EdgarError("Couldn't reach SEC EDGAR: timeout")

    llm = CountingLLM([SUMMARY, BRIEF])
    app = create_app(FakeRetriever(make_papers()), llm, BriefStore(tmp_path / "b2"),
                     market_scans=MarketScanStore(tmp_path / "s2"), edgar=DownEdgar([]))
    client = TestClient(app)
    brief_id = client.post("/api/ask", json={"question": "Q?"}).json()["id"]
    response = run_scan(client, brief_id)
    assert response.status_code == 502 and "SEC EDGAR" in response.json()["detail"]


def test_market_sections_match_prompt():
    from src.translation.market_prompts import MARKET_SCAN_SYSTEM_PROMPT
    for section in MARKET_SECTIONS:
        assert f"## {section}" in MARKET_SCAN_SYSTEM_PROMPT
