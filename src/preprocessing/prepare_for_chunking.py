"""Preprocessing hand-off for issue #12 (the part before chunking).

papers_clean (Chythra)  ->  chunk_input.jsonl  ->  Alena's chunker

It decides WHAT text goes into chunking and attaches the metadata. It does NOT
split text into chunks. That is Alena's part.

What it does (all rules come from Chythra's preprocessing README):
  * keep only rows with is_usable == True
  * keep the main-text sections only: skip front_matter, acknowledgments,
    back_matter, references, appendix (same as her body_text)
  * one output row per kept section, in reading order, with
    paper_id, title, authors, arxiv_url, section (number + heading),
    section_type, est_tokens, text
  * if a paper has no abstract section in the body (the abstract is inside the
    title block / front_matter), add one row from abstract_clean, her "tier 1" text
  * papers flagged no_headings (or with no sections): one row with the whole body_text

It does not clean text again. Cleaning is Chythra's step and is already in papers_clean.

Usage:
    python prepare_for_chunking.py papers_clean.jsonl chunk_input.jsonl
    python prepare_for_chunking.py papers_clean.parquet chunk_input.jsonl --append
"""
import json
import sys

# same as EXCLUDED_FROM_BODY in src/preprocessing/sections.py
EXCLUDED_FROM_BODY = {"front_matter", "acknowledgments", "back_matter",
                      "references", "appendix"}


def est_tokens(text):
    """Same estimate as `est_tokens` in papers_clean: characters / 4."""
    return len(text) // 4


def load_papers(path):
    """Read papers_clean as .jsonl or .parquet (parquet needs pandas + pyarrow)."""
    if path.endswith(".parquet"):
        import pandas as pd
        papers = pd.read_parquet(path).to_dict("records")
        for p in papers:
            secs = p.get("sections")
            p["sections"] = [dict(x) for x in (secs if secs is not None else [])]
            p["authors"] = list(p["authors"])
            qi = p.get("quality_issues")
            p["quality_issues"] = list(qi) if qi is not None else []
        return papers
    return [json.loads(l) for l in open(path)]


def prepare_paper(paper):
    meta = {
        "paper_id": paper["arxiv_id"],
        "title": paper["title"],
        "authors": list(paper["authors"]),
        "arxiv_url": paper["abs_url"],
    }
    rows = []
    for s in paper.get("sections") or []:
        if s["section_type"] in EXCLUDED_FROM_BODY or not s["text"].strip():
            continue
        heading = " ".join(p for p in (s.get("number", ""), s.get("heading", "")) if p)
        rows.append({"section": heading, "section_type": s["section_type"],
                     "source": "body", "text": s["text"].strip()})

    issues = list(paper.get("quality_issues") or [])
    if "no_headings" in issues or not rows:
        body = (paper.get("body_text") or "").strip()
        rows = ([{"section": "", "section_type": "body", "source": "body_text",
                  "text": body}] if body else [])

    abstract = (paper.get("abstract_clean") or "").strip()
    if abstract and not any(r["section_type"] == "abstract" for r in rows):
        rows.insert(0, {"section": "Abstract (arXiv metadata)",
                        "section_type": "abstract", "source": "abstract_clean",
                        "text": abstract})

    out = []
    for i, r in enumerate(rows):
        out.append({**meta, "section_id": f"{paper['arxiv_id']}_sec{i:02d}",
                    **r, "est_tokens": est_tokens(r["text"])})
    return out


def main():
    import argparse
    import os
    ap = argparse.ArgumentParser(description="Prepare papers_clean for chunking")
    ap.add_argument("src", help="papers_clean.jsonl or papers_clean.parquet")
    ap.add_argument("dst", help="output chunk_input.jsonl")
    ap.add_argument("--append", action="store_true",
                    help="keep existing rows and only add papers not yet in dst")
    a = ap.parse_args()

    done = set()
    if a.append and os.path.exists(a.dst):
        done = {json.loads(l)["paper_id"] for l in open(a.dst)}
    papers = load_papers(a.src)
    n_papers = n_rows = n_skipped = 0
    with open(a.dst, "a" if a.append else "w") as f:
        for p in papers:
            if not p.get("is_usable", True):
                n_skipped += 1
                continue
            if p["arxiv_id"] in done:
                continue
            rows = prepare_paper(p)
            if not rows:
                n_skipped += 1
                continue
            n_papers += 1
            n_rows += len(rows)
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{n_papers} new papers -> {n_rows} sections -> {a.dst} "
          f"({len(done)} already done, {n_skipped} skipped as unusable/empty)")


if __name__ == "__main__":
    main()
