# tests for the arXiv API helper and day-by-day ingestion; arXiv is never called

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from src.ingestion import arxiv_api, fetch_metadata as fm, pipeline


def feed(entries, total=None):
    body = "".join(entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>{len(entries) if total is None else total}</opensearch:totalResults>
  {body}
</feed>""".encode()


def entry(arxiv_id, published="2026-11-01T10:00:00Z"):
    return f"""<entry>
    <id>http://arxiv.org/abs/{arxiv_id}</id>
    <updated>{published}</updated><published>{published}</published>
    <title>A  title
      on two lines</title>
    <summary> The abstract. </summary>
    <author><name>Ada Lovelace</name></author><author><name>Alan Turing</name></author>
    <link href="http://arxiv.org/abs/{arxiv_id}" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/{arxiv_id}" rel="related" type="application/pdf"/>
    <arxiv:primary_category term="cs.AI"/>
    <category term="cs.AI"/><category term="cs.CL"/>
  </entry>"""


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status_code, self.content, self.headers = status, body, headers or {}

    def raise_for_status(self):
        raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def responses(monkeypatch):
    """queue of FakeResponses; records the params of every request and every wait"""
    state = {"queue": [], "params": [], "waits": []}

    def fake_get(url, params, timeout, headers):
        state["params"].append(params)
        assert headers["User-Agent"]
        return state["queue"].pop(0)

    monkeypatch.setattr(arxiv_api.requests, "get", fake_get)
    monkeypatch.setattr(arxiv_api.time, "sleep", lambda s: state["waits"].append(s))
    monkeypatch.setattr(arxiv_api, "_last_request", 0.0)
    return state


# ---------- requests and back-off ----------

def test_429_backs_off_longer_each_time(responses):
    responses["queue"] = [FakeResponse(429), FakeResponse(503), FakeResponse(200, b"ok")]
    assert arxiv_api.get({"q": 1}, sleep=responses["waits"].append) == b"ok"
    backoffs = [w for w in responses["waits"] if w >= arxiv_api.FIRST_WAIT]
    assert backoffs == [15, 30]


def test_retry_after_header_is_followed(responses):
    responses["queue"] = [FakeResponse(429, headers={"Retry-After": "90"}), FakeResponse(200, b"ok")]
    arxiv_api.get({}, sleep=responses["waits"].append)
    assert 90 in responses["waits"]


def test_gives_up_with_arxiv_unavailable(responses):
    responses["queue"] = [FakeResponse(429)] * 3
    with pytest.raises(arxiv_api.ArxivUnavailable):
        arxiv_api.get({}, max_retries=3, sleep=responses["waits"].append)


def test_other_errors_are_not_retried(responses):
    responses["queue"] = [FakeResponse(400)]
    with pytest.raises(RuntimeError, match="400"):
        arxiv_api.get({}, sleep=responses["waits"].append)


# ---------- parsing and paging ----------

def test_parse_entry_matches_the_pipeline_fields(responses):
    responses["queue"] = [FakeResponse(200, feed([entry("2611.00001v2")]))]
    [paper] = fm.fetch_metadata("cat:cs.AI", 10, date(2026, 11, 1), date(2026, 11, 1))
    assert paper["arxiv_id"] == "2611.00001v2"
    assert paper["title"] == "A title on two lines" and paper["abstract"] == "The abstract."
    assert paper["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert paper["primary_category"] == "cs.AI" and paper["categories"] == ["cs.AI", "cs.CL"]
    assert paper["published"] == datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
    assert paper["pdf_url"] == "http://arxiv.org/pdf/2611.00001v2"


def test_window_query_and_paging(responses, monkeypatch):
    monkeypatch.setattr(fm, "PAGE_SIZE", 2)
    responses["queue"] = [
        FakeResponse(200, feed([entry("2611.00001v1"), entry("2611.00002v1")], total=3)),
        FakeResponse(200, feed([entry("2611.00003v1")], total=3)),
    ]
    papers = fm.fetch_metadata("cat:cs.AI", 100, date(2026, 11, 1), date(2026, 11, 2))
    assert [p["arxiv_id"] for p in papers] == ["2611.00001v1", "2611.00002v1", "2611.00003v1"]
    first, second = responses["params"]
    assert first["search_query"] == "cat:cs.AI AND submittedDate:[202611010000 TO 202611022359]"
    assert first["sortOrder"] == "ascending" and second["start"] == 2


def test_without_since_asks_for_the_newest(responses):
    responses["queue"] = [FakeResponse(200, feed([entry("2611.00009v1")]))]
    fm.fetch_metadata("cat:cs.AI", 5)
    assert responses["params"][0]["search_query"] == "cat:cs.AI"
    assert responses["params"][0]["sortOrder"] == "descending"
    assert responses["params"][0]["max_results"] == 5


def test_days_between():
    assert list(fm.days_between(date(2026, 10, 30), date(2026, 11, 1))) == [
        date(2026, 10, 30), date(2026, 10, 31), date(2026, 11, 1)]


# ---------- day-by-day ingestion ----------

DAY1 = date(2026, 11, 1)


def paper(arxiv_id, day):
    return {"arxiv_id": arxiv_id, "title": "t", "abstract": "a", "authors": ["A"],
            "primary_category": "cs.AI", "categories": ["cs.AI"],
            "published": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
            "updated": datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
            "pdf_url": "", "abs_url": ""}


@pytest.fixture
def by_day(monkeypatch):
    """three days with two papers each; days listed in state["down"] raise like a 429"""
    days = {DAY1 + timedelta(days=d): [paper(f"2611.{d}{i}v1", DAY1 + timedelta(days=d)) for i in range(2)]
            for d in range(3)}
    state = {"down": set(), "asked": []}

    def fake_fetch(category, max_results, since, until):
        state["asked"].append(since)
        if since in state["down"]:
            raise arxiv_api.ArxivUnavailable("429")
        return [dict(p) for p in days.get(since, [])]

    def fake_download(papers, raw_pdf_dir):
        for p in papers:
            p["pdf_path"], p["download_status"] = "x.pdf", "downloaded"
        return papers

    def fake_extract(papers):
        for p in papers:
            p["extracted_text"], p["extraction_status"] = "text", "extracted"
        return papers

    monkeypatch.setattr(pipeline, "fetch_metadata", fake_fetch)
    monkeypatch.setattr(pipeline, "days_between", lambda since: iter(sorted(days)))
    monkeypatch.setattr(pipeline, "download_all", fake_download)
    monkeypatch.setattr(pipeline, "extract_all", fake_extract)
    return state


def test_each_day_is_saved_before_the_next_is_fetched(by_day, tmp_path):
    path = tmp_path / "papers.parquet"
    by_day["down"] = {DAY1 + timedelta(days=2)}

    with pytest.raises(arxiv_api.ArxivUnavailable):
        pipeline.run_pipeline(dataset_path=str(path), raw_pdf_dir=str(tmp_path), since=DAY1, batch_size=10)

    # arXiv refused day 3, but days 1 and 2 are kept
    assert sorted(pd.read_parquet(path)["arxiv_id"]) == ["2611.00v1", "2611.01v1", "2611.10v1", "2611.11v1"]

    # the next run fills in day 3 without redoing the others
    by_day["down"] = set()
    df = pipeline.run_pipeline(dataset_path=str(path), raw_pdf_dir=str(tmp_path), since=DAY1, batch_size=10)
    assert len(df) == 6 and df["arxiv_id"].is_unique


def test_max_papers_stops_across_days(by_day, tmp_path, capsys):
    path = str(tmp_path / "papers.parquet")
    pipeline.run_pipeline(dataset_path=path, raw_pdf_dir=str(tmp_path), since=DAY1, max_papers=3, batch_size=10)

    assert sorted(pd.read_parquet(path)["arxiv_id"]) == ["2611.00v1", "2611.01v1", "2611.10v1"]
    assert by_day["asked"] == [DAY1, DAY1 + timedelta(days=1)]          # day 3 never fetched
    assert ", 1 more left for the next run" in capsys.readouterr().out  # read by pull_recent_papers.sh
