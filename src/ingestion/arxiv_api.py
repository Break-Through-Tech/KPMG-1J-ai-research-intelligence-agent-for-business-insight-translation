# talks to the arXiv API (export.arxiv.org/api/query) for the metadata fetch and the coverage check
#
# arXiv rate-limits busy clients (HTTP 429) and is sometimes overloaded (503). GitHub's shared
# runners hit this a lot, so every request here:
#   - waits 3 seconds after the previous one, as arXiv asks
#   - on 429/503, backs off for longer each time (15s, 30s, 60s... up to 5 minutes), or for as
#     long as arXiv's Retry-After header says
#   - sends a User-Agent (set ARXIV_USER_AGENT to add a contact, which arXiv recommends)

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"

RETRY_CODES = {406, 429, 500, 502, 503}
MIN_INTERVAL = 3        # seconds between requests
FIRST_WAIT = 15         # first back-off after a 429/503, doubled each time
MAX_WAIT = 300
USER_AGENT = os.environ.get("ARXIV_USER_AGENT", "research-corpus-updater/1.0 (python-requests)")

_last_request = 0.0
# whether any request in this process has worked; if none has, a refusal means arXiv is
# blocking this machine (GitHub runners share IPs), not a brief outage partway through
_ever_succeeded = False


class ArxivUnavailable(RuntimeError):
    """arXiv couldn't be reached after retrying (this is not the same as papers missing)"""


def ever_succeeded():
    return _ever_succeeded


def _retry_after(resp):
    try:
        return max(0, int(resp.headers.get("Retry-After", "")))
    except (TypeError, ValueError, AttributeError):
        return None


def get(params, max_retries=6, sleep=time.sleep):
    """the response body for one API query, retrying 429/503 and network errors with back-off"""
    global _last_request, _ever_succeeded
    wait = FIRST_WAIT
    status = None
    for attempt in range(1, max_retries + 1):
        gap = MIN_INTERVAL - (time.monotonic() - _last_request)
        if gap > 0:
            sleep(gap)
        try:
            resp = requests.get(API_URL, params=params, timeout=120, headers={"User-Agent": USER_AGENT})
            status = resp.status_code
        except requests.RequestException as e:
            resp, status = None, type(e).__name__
        _last_request = time.monotonic()

        if status == 200:
            _ever_succeeded = True
            return resp.content
        if resp is not None and status not in RETRY_CODES:
            resp.raise_for_status()
        if attempt < max_retries:
            delay = min(_retry_after(resp) or wait, MAX_WAIT)
            print(f"arXiv returned {status}, retrying in {delay}s ({attempt}/{max_retries})")
            sleep(delay)
            wait = min(wait * 2, MAX_WAIT)
    raise ArxivUnavailable(f"arXiv API still failing after {max_retries} attempts (last: {status})")


def window_query(category, start, end):
    """category papers first submitted between two datetimes (minute precision, UTC)"""
    return f"{category} AND submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"


def _time(text):
    return datetime.fromisoformat(text.strip().replace("Z", "+00:00"))


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_entry(entry):
    """one Atom <entry> as the metadata dict the ingestion pipeline uses"""
    abs_url = entry.findtext(f"{ATOM}id").strip()
    pdf_url = next((link.get("href") for link in entry.findall(f"{ATOM}link") if link.get("title") == "pdf"),
                   abs_url.replace("/abs/", "/pdf/"))
    primary = entry.find(f"{ARXIV}primary_category")
    return {
        "arxiv_id": abs_url.rsplit("/abs/", 1)[-1],
        "title": _clean(entry.findtext(f"{ATOM}title")),
        "abstract": _clean(entry.findtext(f"{ATOM}summary")),
        "authors": [_clean(a.findtext(f"{ATOM}name")) for a in entry.findall(f"{ATOM}author")],
        "primary_category": primary.get("term") if primary is not None else "",
        "categories": [c.get("term") for c in entry.findall(f"{ATOM}category")],
        "published": _time(entry.findtext(f"{ATOM}published")),
        "updated": _time(entry.findtext(f"{ATOM}updated")),
        "pdf_url": pdf_url,
        "abs_url": abs_url,
    }


def search_pages(query, page_size, max_results=None, newest_first=False, get=get):
    """yields one page of Atom entries at a time, by submission date"""
    offset, total = 0, None
    while total is None or offset < total:
        if max_results is not None and offset >= max_results:
            return
        size = page_size if max_results is None else min(page_size, max_results - offset)
        root = ET.fromstring(get({
            "search_query": query, "start": offset, "max_results": size,
            "sortBy": "submittedDate", "sortOrder": "descending" if newest_first else "ascending",
        }))
        total = int(root.findtext(f"{OPENSEARCH}totalResults", "0"))
        entries = root.findall(f"{ATOM}entry")
        if not entries:
            return
        yield entries
        offset += len(entries)
