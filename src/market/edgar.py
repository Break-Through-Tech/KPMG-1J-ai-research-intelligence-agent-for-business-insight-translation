# SEC EDGAR full-text search: which public companies mention a technology in
# their filings, and what they say about it. Free, no account; SEC asks every
# caller to name itself in the User-Agent header (with a contact email) and to
# stay under 10 requests a second.
#
#   export SEC_USER_AGENT="KPMG 1J research prototype you@school.edu"
#
# https://www.sec.gov/os/accessing-edgar-data

import html
import os
import re
import time
from datetime import date

SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data"

# Annual and quarterly reports, current reports (8-K: deals, launches, press
# releases), their foreign-issuer versions, and IPO registrations
FORMS = ["10-K", "10-Q", "8-K", "20-F", "6-K", "S-1"]

# Hits per search page (EDGAR's fixed page size)
PAGE_SIZE = 100

USER_AGENT_VARIABLE = "SEC_USER_AGENT"
SETUP_MESSAGE = (
    "SEC EDGAR asks every caller to identify itself. Set SEC_USER_AGENT to a name and "
    "contact email, e.g. export SEC_USER_AGENT=\"KPMG 1J research prototype you@school.edu\", "
    "then restart the app."
)

DISPLAY_NAME = re.compile(r"^(?P<name>.*?)\s*(?:\((?P<ticker>[A-Z0-9.\-, ]+)\))?\s*\(CIK \d+\)\s*$")


class EdgarError(RuntimeError):
    """EDGAR couldn't be reached or answered with an error."""


def parse_filing(hit):
    """One search hit -> the fields the market scan shows and cites."""
    source = hit["_source"]
    adsh, _, filename = hit["_id"].partition(":")
    cik = str(int(source["ciks"][0])) if source.get("ciks") else ""
    folder = f"{ARCHIVE_URL}/{cik}/{adsh.replace('-', '')}"

    match = DISPLAY_NAME.match((source.get("display_names") or [""])[0])
    company = match.group("name").strip() if match else (source.get("display_names") or [""])[0]
    ticker = (match.group("ticker") or "").split(",")[0].strip() if match else ""

    return {
        "company": company,
        "ticker": ticker,
        "cik": cik,
        "form": source.get("form") or source.get("file_type") or "",
        "document_type": source.get("file_type") or "",
        "description": source.get("file_description") or "",
        "filed": source.get("file_date") or "",
        "period": source.get("period_ending") or "",
        "items": source.get("items") or [],
        "sics": source.get("sics") or [],
        "adsh": adsh,
        "url": f"{folder}/{filename}",
        "index_url": f"{folder}/{adsh}-index.htm",
        "score": hit.get("_score") or 0,
    }


def html_to_text(raw):
    """Readable text from a filing document (HTML, inline XBRL or plain text)."""
    text = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", raw)
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", text)
    # block tags end a sentence-ish unit; others just separate words
    text = re.sub(r"(?i)</?(p|div|br|tr|li|h[1-6]|table)\b[^>]*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


class EdgarClient:

    def __init__(self, user_agent, session=None, min_interval=0.15, max_bytes=15_000_000,
                 timeout=30, sleep=time.sleep, clock=time.monotonic):
        if not user_agent or not user_agent.strip():
            raise ValueError(SETUP_MESSAGE)

        if session is None:
            import requests

            session = requests.Session()

        self.session = session
        self.headers = {"User-Agent": user_agent.strip(), "Accept-Encoding": "gzip, deflate"}
        # SEC allows 10 requests a second; stay under it
        self.min_interval = min_interval
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.sleep = sleep
        self.clock = clock
        self._last = None

    def _wait(self):
        if self._last is not None:
            gap = self.clock() - self._last
            if gap < self.min_interval:
                self.sleep(self.min_interval - gap)
        self._last = self.clock()

    def _get(self, url, params=None, stream=False):
        self._wait()
        try:
            response = self.session.get(url, params=params, headers=self.headers,
                                        timeout=self.timeout, stream=stream)
        except Exception as error:
            raise EdgarError(f"Couldn't reach SEC EDGAR: {error}") from error
        if response.status_code == 403:
            raise EdgarError("SEC EDGAR refused the request (403). Check that SEC_USER_AGENT "
                             "has a name and a real contact email.")
        if response.status_code == 429:
            raise EdgarError("SEC EDGAR is rate limiting this app. Wait a minute and try again.")
        if response.status_code >= 400:
            raise EdgarError(f"SEC EDGAR returned an error ({response.status_code}).")
        return response

    def search(self, query, since, until, forms=FORMS, page=0):
        """
        Filings whose text matches query, filed between since and until (dates).
        query: EDGAR full-text syntax; "quoted phrases" match exactly and
               space-separated terms must all appear.
        Returns {"total": int, "filings": [parse_filing(...)]}, best match first.
        """
        params = {
            "q": query,
            "forms": ",".join(forms),
            "dateRange": "custom",
            "startdt": _iso(since),
            "enddt": _iso(until),
        }
        if page:
            params["from"] = page * PAGE_SIZE

        data = self._get(SEARCH_URL, params=params).json()
        hits = data.get("hits", {})
        return {
            "total": int((hits.get("total") or {}).get("value") or 0),
            "filings": [parse_filing(hit) for hit in hits.get("hits", [])],
        }

    def count(self, query, since, until, forms=FORMS):
        return self.search(query, since, until, forms)["total"]

    def document_text(self, filing):
        """The filing document as text, reading at most max_bytes of it."""
        response = self._get(filing["url"], stream=True)
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=256 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size >= self.max_bytes:
                break
        response.close()
        raw = b"".join(chunks).decode(response.encoding or "utf-8", errors="ignore")
        return html_to_text(raw)


def _iso(value):
    return value.isoformat() if isinstance(value, date) else str(value)


def edgar_from_env():
    """An EdgarClient if SEC_USER_AGENT is set (in the environment or .env), else None."""
    from src.pipeline.llm import load_env_file

    load_env_file()
    user_agent = os.environ.get(USER_AGENT_VARIABLE, "").strip()
    return EdgarClient(user_agent) if user_agent else None
