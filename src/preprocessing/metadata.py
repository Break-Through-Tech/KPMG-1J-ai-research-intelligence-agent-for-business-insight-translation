# cleans the arxiv metadata columns and removes duplicate versions of the same paper
# ingestion dedupes on the full arxiv_id ("2609.26780v1"), so v1 and v2 of one paper can both end up in the dataset

import re
import pandas as pd

from .normalize import normalize_abstract

VERSION_RE = re.compile(r"v(\d+)$")


def split_version(arxiv_id: str) -> tuple[str, int]:
    """'2609.26780v2' -> ('2609.26780', 2), ids without a version count as v1"""
    match = VERSION_RE.search(arxiv_id)
    if not match:
        return arxiv_id, 1
    return arxiv_id[:match.start()], int(match.group(1))


def _to_list(value):
    # parquet gives list columns back as numpy arrays
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [str(v) for v in value]


def clean_metadata(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """returns the cleaned frame and how many older versions were dropped"""
    df = df.copy()

    ids = df["arxiv_id"].astype(str).map(split_version)
    df["base_id"] = ids.str[0]
    df["version"] = ids.str[1].astype(int)

    # keep the newest version of each paper, preferring rows that ingested completely
    df["_complete"] = (df["ingestion_status"] == "complete").astype(int)
    before = len(df)
    df = (df.sort_values(["base_id", "_complete", "version"])
            .drop_duplicates(subset="base_id", keep="last")
            .drop(columns="_complete"))
    n_dropped = before - len(df)

    df["published"] = pd.to_datetime(df["published"], utc=True)
    df["updated"] = pd.to_datetime(df["updated"], utc=True)
    df["published_date"] = df["published"].dt.date
    df["year_month"] = df["published"].dt.strftime("%Y-%m")

    df["authors"] = df["authors"].map(_to_list)
    df["categories"] = df["categories"].map(_to_list)
    df["author_count"] = df["authors"].map(len)

    df["title"] = df["title"].fillna("").map(lambda t: re.sub(r"\s+", " ", t).strip())
    df["abstract_clean"] = df["abstract"].map(normalize_abstract)

    df = df.sort_values("published", ascending=False).reset_index(drop=True)
    return df, n_dropped
