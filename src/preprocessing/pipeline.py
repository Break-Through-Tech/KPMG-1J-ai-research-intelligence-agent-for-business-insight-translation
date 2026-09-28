# preprocessing pipeline: data/papers.parquet (from ingestion) -> data/papers_clean.parquet
# the raw extracted_text is never modified, so this can be rerun with new rules without redownloading anything

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .boilerplate import remove_page_artifacts
from .metadata import clean_metadata
from .normalize import normalize_text
from .quality import compute_quality
from .sections import build_body_text, split_sections

# columns carried over from ingestion; extracted_text and pdf_path stay in the raw dataset
METADATA_COLUMNS = [
    "arxiv_id", "base_id", "version", "title", "abstract", "abstract_clean", "authors", "author_count",
    "primary_category", "categories", "published", "published_date", "year_month", "updated",
    "pdf_url", "abs_url", "ingestion_status",
]


def preprocess_paper(raw_text, ingestion_status, abstract) -> dict:
    text = normalize_text(raw_text)
    text, n_artifacts = remove_page_artifacts(text)
    sections = split_sections(text)
    body_text = build_body_text(sections)

    result = {
        "body_text": body_text,
        "sections": sections,
        "n_artifact_lines_removed": n_artifacts,
    }
    result.update(compute_quality(raw_text, sections, body_text, ingestion_status, abstract))
    return result


def build_report(clean: pd.DataFrame, n_input: int, n_duplicates: int) -> dict:
    section_types = Counter(s["section_type"] for secs in clean["sections"] for s in secs)
    issues = Counter(i for row in clean["quality_issues"] for i in row)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "papers_in": n_input,
        "duplicate_versions_dropped": n_duplicates,
        "papers_out": len(clean),
        "usable_papers": int(clean["is_usable"].sum()),
        "usable_rate": round(float(clean["is_usable"].mean()), 4) if len(clean) else 0.0,
        "date_range": [str(clean["published_date"].min()), str(clean["published_date"].max())] if len(clean) else [],
        "raw_chars_total": int(clean["raw_char_count"].sum()),
        "body_chars_total": int(clean["body_char_count"].sum()),
        "body_tokens_median": int(clean["est_tokens"].median()) if len(clean) else 0,
        "body_tokens_total_usable": int(clean.loc[clean["is_usable"], "est_tokens"].sum()),
        "artifact_lines_removed": int(clean["n_artifact_lines_removed"].sum()),
        "references_found_rate": round(float(clean["has_references"].mean()), 4) if len(clean) else 0.0,
        "appendix_rate": round(float(clean["has_appendix"].mean()), 4) if len(clean) else 0.0,
        "quality_issues": dict(issues.most_common()),
        "section_types": dict(section_types.most_common()),
        "unusable_papers": clean.loc[~clean["is_usable"], ["arxiv_id", "title"]]
                                .assign(issues=clean.loc[~clean["is_usable"], "quality_issues"])
                                .to_dict("records"),
    }


def run_preprocessing(input_path="data/papers.parquet", output_path="data/papers_clean.parquet",
                      report_path="data/preprocess_report.json") -> pd.DataFrame:
    if not Path(input_path).exists():
        raise FileNotFoundError(f"{input_path} not found, run the ingestion pipeline first")

    raw = pd.read_parquet(input_path)
    if raw.empty:
        raise ValueError(f"{input_path} has no rows")

    df, n_duplicates = clean_metadata(raw)

    processed = [
        preprocess_paper(row.extracted_text, row.ingestion_status, row.abstract_clean)
        for row in df.itertuples(index=False)
    ]
    clean = pd.concat([df[METADATA_COLUMNS], pd.DataFrame(processed)], axis=1)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    clean.to_parquet(output_path, index=False)

    report = build_report(clean, len(raw), n_duplicates)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"preprocessed {report['papers_out']} papers ({report['usable_papers']} usable), "
          f"dropped {n_duplicates} duplicate versions, removed {report['artifact_lines_removed']} artifact lines")
    print(f"wrote {output_path} and {report_path}")
    return clean
