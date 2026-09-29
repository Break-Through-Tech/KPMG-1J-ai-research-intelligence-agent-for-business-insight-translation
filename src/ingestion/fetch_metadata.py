# fetch paper metadata from arXiv
# tries the arXiv API first. If the API keeps returning HTTP 406 (widespread in Sept 2026),
# falls back to arXiv's RSS feed, which lives on a different server (rss.arxiv.org).
# The RSS feed only covers the most recent announcement day, so max_results is capped by that.

import re
import time
from datetime import date, datetime

import feedparser
import requests

API_URL = "https://export.arxiv.org/api/query"
RSS_URL = "https://rss.arxiv.org/atom/{cat}"
HEADERS = {
    # arXiv asks automated clients to identify themselves; put a real contact email here
    "User-Agent": "BTT-KPMG-1J-research-agent/0.1 (mailto:YOUR_EMAIL@bu.edu)",
    "Accept": "application/atom+xml",
}
RETRY_CODES = {406, 429, 500, 502, 503}
PAGE_SIZE = 100


def _get_page(params, max_retries=3):
    wait = 5
    for attempt in range(1, max_retries + 1):
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=60)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code not in RETRY_CODES:
            resp.raise_for_status()
        print(f"arXiv returned {resp.status_code}, retry {attempt}/{max_retries} in {wait}s")
        time.sleep(wait)
        wait *= 2
    raise RuntimeError(f"arXiv API still failing after {max_retries} retries (last status {resp.status_code})")


def _to_datetime(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _clean(s):
    return re.sub(r"\s+", " ", s).strip()


def fetch_metadata(category="cat:cs.AI", max_results=50, since: date | None = None) -> list[dict]:
    try:
        return fetch_from_api(category, max_results, since)
    except RuntimeError as e:
        print(f"{e}\nFalling back to the RSS feed (latest announcement day only)")
        return fetch_from_rss(category, max_results)


def fetch_from_api(category="cat:cs.AI", max_results=50, since: date | None = None) -> list[dict]:
    """returns metadata dicts with arxiv_id, title, abstract, authors, primary_category,
    categories, published, updated, pdf_url, abs_url (same fields as before)"""
    papers = []
    start = 0
    while len(papers) < max_results:
        params = {
            "search_query": category,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": start,
            "max_results": min(PAGE_SIZE, max_results - len(papers)),
        }
        feed = feedparser.parse(_get_page(params))
        if not feed.entries:
            break

        for e in feed.entries:
            published = _to_datetime(e.published)
            if since is not None and published.date() < since:
                return papers  # results are newest first, so nothing after this matches

            abs_url = e.id
            pdf_url = next((l.href for l in e.links if l.get("title") == "pdf"),
                           abs_url.replace("/abs/", "/pdf/"))
            papers.append({
                "arxiv_id": abs_url.rsplit("/abs/", 1)[-1],
                "title": _clean(e.title),
                "abstract": _clean(e.summary),
                "authors": [a.name for a in e.get("authors", [])],
                "primary_category": e.get("arxiv_primary_category", {}).get("term"),
                "categories": [t.term for t in e.get("tags", [])],
                "published": published,
                "updated": _to_datetime(e.updated),
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            })

        start += len(feed.entries)
        time.sleep(3)  # arXiv asks for 3 seconds between requests

    return papers[:max_results]


def fetch_from_rss(category="cat:cs.AI", max_results=50) -> list[dict]:
    """same fields as fetch_from_api, built from rss.arxiv.org.
    Differences: no true published date (uses the announcement date for both dates),
    and primary_category is the first listed category, which I have not confirmed is always the primary."""
    cat = category.replace("cat:", "")
    resp = requests.get(RSS_URL.format(cat=cat), headers=HEADERS, timeout=60)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)

    papers = []
    for e in feed.entries:
        # skip "replace" entries: those are old papers getting a new version, not recent research
        if e.get("arxiv_announce_type", "new") not in ("new", "cross"):
            continue
        arxiv_id = e.id.split(":")[-1]                      # oai:arXiv.org:2609.30264v1 -> 2609.30264v1
        abstract = e.summary.split("Abstract:", 1)[-1]      # drop the "arXiv:... Announce Type: new" prefix
        categories = [t.term for t in e.get("tags", [])]
        announced = _to_datetime(e.updated)
        papers.append({
            "arxiv_id": arxiv_id,
            "title": _clean(e.title),
            "abstract": _clean(abstract),
            "authors": [a.strip() for a in e.get("author", "").split(",") if a.strip()],
            "primary_category": categories[0] if categories else None,
            "categories": categories,
            "published": announced,
            "updated": announced,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
        })
        if len(papers) >= max_results:
            break
    return papers