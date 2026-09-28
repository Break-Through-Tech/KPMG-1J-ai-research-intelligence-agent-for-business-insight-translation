# unit tests for src/preprocessing, run from the project root with: python -m pytest tests/

import pandas as pd

from src.preprocessing.boilerplate import remove_page_artifacts
from src.preprocessing.metadata import clean_metadata, split_version
from src.preprocessing.normalize import normalize_abstract, normalize_text
from src.preprocessing.pipeline import preprocess_paper
from src.preprocessing.quality import compute_quality
from src.preprocessing.sections import build_body_text, classify_heading, clean_heading, split_sections


# ---------- normalize ----------

def test_picture_blocks_and_placeholders_removed():
    raw = "before\n<!-- Start of picture text -->junk<br>junk<!-- End of picture text -->\n[Picture Omitted]\n\nFigure 1: caption"
    out = normalize_text(raw)
    assert "junk" not in out and "Picture Omitted" not in out
    assert "Figure 1: caption" in out


def test_italic_math_is_collapsed():
    assert normalize_text("speedups of 2 _._ 23 _×_ after 200 steps") == "speedups of 2.23 × after 200 steps"


def test_bold_and_html_markup_stripped():
    out = normalize_text("**Trang Nguyen**<sup>1</sup> , a<br>b and x<sup>2</sup> and 10<sup>-3</sup>")
    assert out == "Trang Nguyen , a b and x^2 and 10^-3"


def test_unicode_is_normalized():
    # math italic p, the fi ligature, a replacement char and a zero width space
    assert normalize_text("𝑝 value of the \ufb01rst run\ufffd\u200b") == "p value of the first run"


def test_whitespace_collapsed():
    assert normalize_text("a   b  \n\n\n\n\nc") == "a b\n\nc"


def test_empty_text():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_normalize_abstract():
    assert normalize_abstract("We   use \\textit{LLMs}\nfor  $x^2$ tasks. ") == "We use LLMs for $x^2$ tasks."
    assert normalize_abstract("S\\&P 500 firms, 34\\% of variance") == "S&P 500 firms, 34% of variance"


# ---------- boilerplate ----------

def _paper_with_running_heads():
    pages = []
    for page in range(1, 6):
        pages.append(f"Preprint\n\nbody text on page {page} about agents.\n\n"
                     f"|a|b|\n|---|---|\n|1|2|\n\n{page}\n\n{page * 2} O. Nepal et al.")
    return "\n\n".join(pages)


def test_running_heads_and_page_numbers_removed():
    text, removed = remove_page_artifacts(_paper_with_running_heads())
    assert "Preprint" not in text
    assert "Nepal" not in text
    assert "\n3\n" not in text
    assert removed == 15


def test_table_rows_are_kept():
    text, _ = remove_page_artifacts(_paper_with_running_heads())
    assert text.count("|1|2|") == 5


def test_running_head_rendered_as_heading_is_removed():
    text = _paper_with_running_heads() + "\n\n### 12 O. Nepal et al.\n\nlast page"
    out, _ = remove_page_artifacts(text)
    assert "Nepal" not in out and "last page" in out


def test_code_blocks_untouched():
    text = "intro\n```\n1\n```\nPreprint\nx\nPreprint\ny\nPreprint"
    out, _ = remove_page_artifacts(text)
    assert "```\n1\n```" in out


def test_non_repeated_short_line_kept():
    out, removed = remove_page_artifacts("Preprint\n\nsome text\n\nmore text")
    assert "Preprint" in out and removed == 0


# ---------- sections ----------

def test_clean_heading():
    assert clean_heading("**3.2 Threat Model**") == ("3.2", "Threat Model")
    assert clean_heading("B.1 Hyperparameter Settings") == ("B.1", "Hyperparameter Settings")
    assert clean_heading("A2M: Trace-Optimized Agent Hijacking") == ("", "A2M: Trace-Optimized Agent Hijacking")


def test_classify_heading():
    assert classify_heading("References") == "references"
    assert classify_heading("REFERENCES") == "references"
    assert classify_heading("Reference-free evaluation") != "references"
    assert classify_heading("Limitations and Future Work") == "limitations"
    assert classify_heading("Related Work") == "related_work"
    assert classify_heading("Acknowledgments") == "acknowledgments"
    assert classify_heading("Something Unusual") == "other"
    assert classify_heading("Conclusion and Code Availability") == "conclusion"
    assert classify_heading("Code Availability") == "back_matter"
    assert classify_heading("AI Use Statement") == "back_matter"


SAMPLE_PAPER = """# **A Great Paper Title**

Jane Doe, University of Somewhere, jane@example.com

## **Abstract**

We study things.

## **1 Introduction**

Intro text.

## **2 Our Approach**

Approach text.

### **2.1 Phase I: Something**

Phase text.

## **3 Experiments**

### **3.1 Main Numbers**

Numbers text.

## **4 Conclusion**

Conclusion text.

## **Acknowledgments**

Thanks.

## **References**

- A. Author. A paper. 2024.

## **A Additional Details**

### **A.1 Hyperparameters**

Appendix text.
"""


def test_split_sections_types():
    types = {s["heading"]: s["section_type"] for s in split_sections(SAMPLE_PAPER)}
    assert types["A Great Paper Title"] == "front_matter"
    assert types["Abstract"] == "abstract"
    assert types["Introduction"] == "introduction"
    assert types["Our Approach"] == "method"
    assert types["Phase I: Something"] == "method"        # inherits from 2
    assert types["Main Numbers"] == "experiments"         # inherits from 3
    assert types["Conclusion"] == "conclusion"
    assert types["Acknowledgments"] == "acknowledgments"
    assert types["References"] == "references"
    assert types["Additional Details"] == "appendix"
    assert types["Hyperparameters"] == "appendix"


def test_body_text_excludes_front_matter_references_and_appendix():
    body = build_body_text(split_sections(SAMPLE_PAPER))
    for kept in ("## Abstract", "## 1 Introduction", "### 2.1 Phase I: Something", "Conclusion text."):
        assert kept in body
    for dropped in ("jane@example.com", "A Great Paper Title", "Thanks.", "A. Author", "Appendix text."):
        assert dropped not in body


def test_bold_pseudo_references_heading():
    text = "## 1 Introduction\n\nIntro.\n\n**References**\n\n- A. Author. 2024.\n\n## A Appendix stuff\n\nMore."
    types = [s["section_type"] for s in split_sections(text)]
    assert types == ["introduction", "references", "appendix"]


def test_lettered_sections_after_conclusion_are_appendix():
    text = "## 1 Introduction\n\nx\n\n## 5 Conclusion\n\ny\n\n## B Proofs\n\nz"
    assert [s["section_type"] for s in split_sections(text)][-1] == "appendix"


def test_sections_do_not_inherit_from_abstract():
    # abstract rendered one level above the numbered sections
    text = "# Abstract\n\nabs\n\n## 1 Introduction\n\nx\n\n## 5 Our agents\n\ny\n\n## 6 Related work\n\nz"
    types = [s["section_type"] for s in split_sections(text)]
    assert types == ["abstract", "introduction", "other", "related_work"]


def test_back_matter_excluded():
    text = ("## 1 Introduction\n\nx\n\n## 8 Conclusion\n\ny\n\n## CRediT authorship contribution statement\n\nz\n\n"
            "## Data availability\n\nw\n\n## References\n\n- ref")
    sections = split_sections(text)
    assert [s["section_type"] for s in sections][2:4] == ["back_matter", "back_matter"]
    assert "Data availability" not in build_body_text(sections)


def test_supplementary_heading_before_references_starts_appendix():
    text = "## 1 Introduction\n\nx\n\n## Supplementary Material\n\ny\n\n## 2 BraTS2020\n\nz"
    assert [s["section_type"] for s in split_sections(text)] == ["introduction", "appendix", "appendix"]


def test_orphan_bold_in_tables_removed():
    assert normalize_text("|Model|Solo MAE **|N=5 ** MAE|") == "|Model|Solo MAE |N=5 MAE|"


def test_no_headings():
    sections = split_sections("just a block of text with no headings")
    assert len(sections) == 1 and sections[0]["section_type"] == "front_matter"


# ---------- quality ----------

def test_short_body_is_not_usable():
    q = compute_quality("x" * 100, [], "x" * 100, "complete", "an abstract")
    assert not q["is_usable"] and "short_body" in q["quality_issues"]


def test_failed_ingestion_is_not_usable():
    q = compute_quality(None, [], "", "failed", "an abstract")
    assert not q["is_usable"]
    assert {"ingestion_not_complete", "no_text"} <= set(q["quality_issues"])


def test_replacement_chars_flagged():
    raw = "a" * 900 + "\ufffd" * 100
    q = compute_quality(raw, [], "a" * 6000, "complete", "abs")
    assert "high_replacement_chars" in q["quality_issues"] and not q["is_usable"]


def test_good_paper_is_usable():
    result = preprocess_paper(SAMPLE_PAPER.replace("Intro text.", "Intro text. " * 600), "complete", "abs")
    assert result["is_usable"], result["quality_issues"]
    assert result["has_references"] and result["has_appendix"]


# ---------- metadata ----------

def test_split_version():
    assert split_version("2609.26780v2") == ("2609.26780", 2)
    assert split_version("2609.26780") == ("2609.26780", 1)


def _meta_row(arxiv_id, status="complete"):
    return {
        "arxiv_id": arxiv_id, "title": " A  title\n", "abstract": "An  abstract.", "authors": ["A", "B"],
        "primary_category": "cs.AI", "categories": ["cs.AI"], "published": "2026-09-22T10:00:00Z",
        "updated": "2026-09-22T10:00:00Z", "pdf_url": "", "abs_url": "", "ingestion_status": status,
    }


def test_dedupe_keeps_latest_version():
    df = pd.DataFrame([_meta_row("2609.00001v1"), _meta_row("2609.00001v2"), _meta_row("2609.00002v1")])
    clean, dropped = clean_metadata(df)
    assert dropped == 1
    assert sorted(clean["arxiv_id"]) == ["2609.00001v2", "2609.00002v1"]


def test_dedupe_prefers_complete_ingestion():
    df = pd.DataFrame([_meta_row("2609.00001v1"), _meta_row("2609.00001v2", status="failed")])
    clean, _ = clean_metadata(df)
    assert clean["arxiv_id"].tolist() == ["2609.00001v1"]


def test_metadata_fields():
    clean, _ = clean_metadata(pd.DataFrame([_meta_row("2609.00001v1")]))
    row = clean.iloc[0]
    assert row["title"] == "A title"
    assert row["abstract_clean"] == "An abstract."
    assert row["author_count"] == 2
    assert row["year_month"] == "2026-09"
