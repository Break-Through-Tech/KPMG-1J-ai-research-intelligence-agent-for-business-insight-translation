# fetches paper metadata from the arXiv API (requests and retries are in arxiv_api.py)

from datetime import date, datetime, time, timedelta, timezone

from . import arxiv_api

PAGE_SIZE = 500   # fewer, larger requests: a busy day of cs.AI fits in one


def fetch_metadata(category="cat:cs.AI", max_results=50, since: date | None = None,
                   until: date | None = None) -> list[dict]:
    """metadata dicts (arxiv_id, title, abstract, authors, primary_category, categories, published,
    updated, pdf_url, abs_url). With since, every paper first submitted from since to until (default
    today), oldest first; without it, the newest max_results papers."""
    if since is None:
        query, newest_first = category, True
    else:
        until = until or datetime.now(timezone.utc).date()
        start = datetime.combine(since, time.min, tzinfo=timezone.utc)
        end = datetime.combine(until, time(23, 59), tzinfo=timezone.utc)
        query, newest_first = arxiv_api.window_query(category, start, end), False

    papers = []
    for entries in arxiv_api.search_pages(query, PAGE_SIZE, max_results, newest_first):
        papers.extend(arxiv_api.parse_entry(e) for e in entries)
    return papers


def days_between(since: date, until: date | None = None):
    """each date from since to until (default today, UTC), oldest first"""
    until = until or datetime.now(timezone.utc).date()
    day = since
    while day <= until:
        yield day
        day += timedelta(days=1)
