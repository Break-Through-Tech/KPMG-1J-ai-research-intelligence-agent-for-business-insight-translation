# per paper quality flags so downstream steps can filter out broken extractions
# ingestion marks a paper "complete" whenever to_markdown returns anything, even a near empty string,
# so this is where silent failures get caught

from .normalize import as_text

MIN_BODY_CHARS = 5_000          # a real cs.AI paper body is tens of thousands of characters
MAX_REPLACEMENT_RATIO = 0.01    # more than 1% unreadable characters means a broken text layer / font encoding

# issues that make a paper unusable for indexing, the rest are informational
BLOCKING_ISSUES = {"ingestion_not_complete", "no_text", "short_body", "high_replacement_chars", "preprocessing_error"}


def compute_quality(raw_text, sections, body_text, ingestion_status, abstract) -> dict:
    raw_text = as_text(raw_text)
    raw_len = len(raw_text)
    replacement_ratio = raw_text.count("�") / raw_len if raw_len else 0.0
    section_types = {s["section_type"] for s in sections}
    n_headed = sum(1 for s in sections if s["level"] > 0)

    issues = []
    if ingestion_status != "complete":
        issues.append("ingestion_not_complete")
    if raw_len == 0:
        issues.append("no_text")
    elif len(body_text) < MIN_BODY_CHARS:
        issues.append("short_body")
    if replacement_ratio > MAX_REPLACEMENT_RATIO:
        issues.append("high_replacement_chars")
    if raw_len and n_headed == 0:
        issues.append("no_headings")
    if raw_len and "references" not in section_types:
        issues.append("no_references_found")
    if not abstract:
        issues.append("missing_abstract")

    return {
        "raw_char_count": raw_len,
        "body_char_count": len(body_text),
        "body_word_count": len(body_text.split()),
        "est_tokens": round(len(body_text) / 4),  # ~4 characters per token for English prose
        "n_sections": n_headed,
        "has_references": "references" in section_types,
        "has_appendix": "appendix" in section_types,
        "replacement_char_ratio": round(replacement_ratio, 5),
        "quality_issues": issues,
        "is_usable": not any(i in BLOCKING_ISSUES for i in issues),
    }
