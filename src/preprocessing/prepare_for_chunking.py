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
    python -m src.preprocessing.prepare_for_chunking   (defaults: data/papers_clean.parquet -> data/chunk_input.jsonl)
    python -m src.preprocessing.prepare_for_chunking papers_clean.parquet chunk_input.jsonl --append
"""
import json
import os

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
        "paper_id": paper["base_id"],          # no version, so a v2 replaces v1 instead of sitting next to it
        "version": int(paper["version"]),
        "title": paper["title"],
        "authors": list(paper["authors"]),
        "arxiv_url": paper["abs_url"],
        # for date/topic filters in the index; str() because json can't write a date object
        "published_date": str(paper["published_date"]),
        "primary_category": paper["primary_category"],
        "categories": list(paper["categories"]),
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
        out.append({**meta, "section_id": f"{paper['base_id']}_sec{i:02d}",
                    **r, "est_tokens": est_tokens(r["text"])})
    return out


def run_prepare(src="data/papers_clean.parquet", dst="data/chunk_input.jsonl", append=False):
    """writes chunk_input.jsonl and returns the rows added this run.
    in append mode, existing rows are kept except papers that now have a newer version,
    since the chunker groups rows by paper_id and would otherwise mix v1 and v2 together"""
    existing = []
    if append and os.path.exists(dst):
        existing = [json.loads(l) for l in open(dst) if l.strip()]
    have = {}  # paper_id -> version already in dst
    for r in existing:
        have[r["paper_id"]] = max(have.get(r["paper_id"], 0), r.get("version", 1))

    new_rows, replaced = [], set()
    n_papers = n_skipped = n_done = 0
    for p in load_papers(src):
        if not p.get("is_usable", True):
            n_skipped += 1
            continue
        if have.get(p["base_id"], 0) >= int(p["version"]):
            n_done += 1
            continue
        rows = prepare_paper(p)
        if not rows:
            n_skipped += 1
            continue
        if p["base_id"] in have:
            replaced.add(p["base_id"])
        n_papers += 1
        new_rows.extend(rows)

    kept = [r for r in existing if r["paper_id"] not in replaced]
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w") as f:
        for r in kept + new_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{n_papers} new papers ({len(replaced)} newer versions) -> {len(new_rows)} sections -> {dst} "
          f"({n_done} already done, {n_skipped} skipped as unusable/empty)")
    return new_rows


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Prepare papers_clean for chunking")
    ap.add_argument("src", nargs="?", default="data/papers_clean.parquet",
                    help="papers_clean.jsonl or papers_clean.parquet")
    ap.add_argument("dst", nargs="?", default="data/chunk_input.jsonl", help="output chunk_input.jsonl")
    ap.add_argument("--append", action="store_true",
                    help="keep existing rows and only add new papers or newer versions")
    a = ap.parse_args()
    run_prepare(a.src, a.dst, a.append)


if __name__ == "__main__":
    main()
