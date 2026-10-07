# "did we miss anything?" check
# asks arXiv for every paper id in a date window and compares that list against our dataset
# ex: python -m src.ingestion.check_coverage --since 2026-10-01 --strict
#
# the window ends at the newest paper we have saved, so a run that stopped early because of
# max_papers only gets checked on what it actually processed (the rest is the next run's job)

import argparse
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
PAGE_SIZE = 2000        # largest page size the arXiv API supports
RETRY_CODES = {406, 429, 500, 502, 503}


def _base_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


class ArxivUnavailable(RuntimeError):
    """arXiv couldn't be reached, so coverage can't be verified (this is not the same as papers missing)"""


def _get(params, max_retries=6):
    wait = 5
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=120)
            status = resp.status_code
        except requests.RequestException as e:
            resp, status = None, type(e).__name__
        if status == 200:
            return resp.content
        if resp is not None and status not in RETRY_CODES:
            resp.raise_for_status()
        if attempt < max_retries:
            print(f"arXiv returned {status}, retrying in {wait}s ({attempt}/{max_retries})")
            time.sleep(wait)
            wait = min(wait * 2, 120)
    raise ArxivUnavailable(f"arXiv API still failing after {max_retries} attempts (last: {status})")


def arxiv_ids_in_window(category: str, start: datetime, end: datetime) -> set[str]:
    """base ids of every paper arXiv lists for the category with a submission time in [start, end]"""
    query = f"{category} AND submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]"
    ids, offset, total = set(), 0, None
    while total is None or offset < total:
        root = ET.fromstring(_get({"search_query": query, "start": offset, "max_results": PAGE_SIZE}))
        total = int(root.findtext(f"{OPENSEARCH}totalResults", "0"))
        entries = root.findall(f"{ATOM}entry")
        if not entries:
            break
        ids.update(_base_id(e.findtext(f"{ATOM}id").rsplit("/", 1)[-1]) for e in entries)
        offset += len(entries)
        if offset < total:
            time.sleep(3)  # arXiv asks for 3 seconds between API calls
    return ids


def check_coverage(dataset_path: str, category: str, since: date, fetch_ids=None) -> dict:
    fetch_ids = fetch_ids or arxiv_ids_in_window
    df = pd.read_parquet(dataset_path, columns=["arxiv_id", "published", "ingestion_status"])
    df["published"] = pd.to_datetime(df["published"], utc=True)
    df["base_id"] = df["arxiv_id"].map(_base_id)

    start = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    # stop just before the newest saved paper: everything older than it should be here
    end = df["published"].max().to_pydatetime().replace(second=0, microsecond=0) - timedelta(minutes=1)
    if end <= start:
        return {"start": start, "end": end, "expected": 0, "missing": [], "incomplete": [], "have": 0}

    expected = fetch_ids(category, start, end)
    window = df[(df["published"] >= start) & (df["published"] <= end + timedelta(minutes=1))]
    have = set(window["base_id"])
    incomplete = sorted(set(window.loc[window["ingestion_status"] != "complete", "base_id"]) & expected)

    return {
        "start": start,
        "end": end,
        "expected": len(expected),
        "missing": sorted(expected - set(df["base_id"])),  # not in the dataset at all
        "incomplete": incomplete,                          # in the dataset but the PDF failed
        "have": len(have & expected),
    }


def main():
    parser = argparse.ArgumentParser(description="check the dataset has every arXiv paper in a date window")
    parser.add_argument("--dataset", default="data/papers.parquet")
    parser.add_argument("--category", default="cat:cs.AI")
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--strict", action="store_true", help="exit with an error if any paper is missing")
    args = parser.parse_args()

    try:
        result = check_coverage(args.dataset, args.category, args.since)
    except ArxivUnavailable as e:
        # a warning, not a failure: a red run should only ever mean papers are actually missing
        print(f"::warning::couldn't reach arXiv to verify coverage for this run, rerun the check later with: python -m src.ingestion.check_coverage --since {args.since} ({e})")
        return
    print(f"coverage check {result['start']:%Y-%m-%d %H:%M} -> {result['end']:%Y-%m-%d %H:%M} UTC: "
          f"arXiv lists {result['expected']} papers, missing {len(result['missing'])}, "
          f"failed PDFs {len(result['incomplete'])}")
    if result["missing"]:
        print("missing:", ", ".join(result["missing"][:20]) + (" ..." if len(result["missing"]) > 20 else ""))
    if result["incomplete"]:
        print("failed PDFs (will be retried next run):", ", ".join(result["incomplete"][:20]))

    if args.strict and result["missing"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
