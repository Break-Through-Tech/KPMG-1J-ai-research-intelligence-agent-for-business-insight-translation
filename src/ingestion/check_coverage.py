# "did we miss anything?" check
# asks arXiv for every paper id in a date window and compares that list against our dataset
# ex: python -m src.ingestion.check_coverage --since 2026-10-01 --strict
#
# the window ends at the newest paper we have saved, so a run that stopped early because of
# max_papers only gets checked on what it actually processed (the rest is the next run's job)

import argparse
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import arxiv_api
from .arxiv_api import ArxivUnavailable  # noqa: F401  (raised from here, imported by callers)

ATOM = arxiv_api.ATOM
PAGE_SIZE = 2000        # largest page size the arXiv API supports


def _base_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def arxiv_ids_in_window(category: str, start: datetime, end: datetime) -> set[str]:
    """base ids of every paper arXiv lists for the category with a submission time in [start, end]"""
    ids = set()
    for entries in arxiv_api.search_pages(arxiv_api.window_query(category, start, end), PAGE_SIZE):
        ids.update(_base_id(e.findtext(f"{ATOM}id").rsplit("/", 1)[-1]) for e in entries)
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
