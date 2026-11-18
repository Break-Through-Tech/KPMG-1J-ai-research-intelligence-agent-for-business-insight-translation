# Automatic checks shown on the brief page. None of them call the LLM.

import re

from src.translation.prompts import BUSINESS_SECTIONS, MAX_BRIEF_WORDS
from src.translation.text_checks import headings, section_text

EVIDENCE_PATTERN = re.compile(r"\b(High|Medium|Low)\b")


def template_check(brief):
    found = headings(brief)
    words = len(brief.split())

    return {
        "ok": found == BUSINESS_SECTIONS and words < MAX_BRIEF_WORDS,
        "headings_ok": found == BUSINESS_SECTIONS,
        "words": words,
        "max_words": MAX_BRIEF_WORDS,
        "sections": len(BUSINESS_SECTIONS),
    }


def evidence_level(brief):
    """'High', 'Medium' or 'Low' from the Evidence Strength section, plus the reason."""
    text = section_text(brief, "Evidence Strength")
    match = EVIDENCE_PATTERN.search(text)

    if not match:
        return {"level": None, "reason": ""}

    # The reason is what follows the level, minus citations and markdown
    reason = text[match.end():].lstrip(".:*- ").strip()
    reason = re.sub(r"\[[^\]]*\]", "", reason)
    reason = re.sub(r"\s+", " ", reason).strip()

    return {"level": match.group(1), "reason": reason}


def citation_check(result, insight):
    """Every paper the summary cites was retrieved, and the brief only cites the summary's papers."""
    not_retrieved = result["citation_check"]["cited_not_retrieved"]
    not_in_summary = insight["citation_check"]["cited_not_in_summary"] if insight else []

    return {
        "ok": not not_retrieved and not not_in_summary,
        "cited_not_retrieved": not_retrieved,
        "cited_not_in_summary": not_in_summary,
    }


def run_checks(result, insight):
    brief = insight["brief"] if insight else ""

    return {
        "citations": citation_check(result, insight),
        "template": template_check(brief),
        "evidence": evidence_level(brief),
        "summary_truncated": bool(result.get("truncated")),
        "brief_truncated": bool(insight and insight.get("truncated")),
    }
