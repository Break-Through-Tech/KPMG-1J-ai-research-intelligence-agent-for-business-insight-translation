# removes page level artifacts that the PDF -> markdown step leaves in the text:
# running headers/footers ("Preprint", "Manuscript submitted to ACM", author/title running heads)
# and bare page numbers. these repeat on every page and add noise to every chunk they land in

import re
from collections import Counter

from .normalize import tidy_whitespace

PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s+)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$", re.I)

MAX_ARTIFACT_LEN = 80   # running heads are short
MIN_REPEATS = 3         # a line has to show up on at least this many pages
MIN_SPREAD = 0.3        # and its occurrences have to span this fraction of the document


def _is_protected(line: str) -> bool:
    # table rows, headings and list bullets repeat legitimately, so never treat them as artifacts
    return line.startswith(("|", "#", "- ", "* ", ">")) or line.startswith("```")


def _line_key(line: str) -> str:
    # "Preprint 12" and "12 Preprint" should count as the same running head,
    # only a leading/trailing page number is ignored so body lines that differ by a number stay distinct
    return re.sub(r"^\d{1,4}\s+|\s+\d{1,4}$", "", line.strip().lower())


def _heading_key(line: str) -> str:
    # "### 4 O. Nepal et al." is a running head that got rendered as a heading
    return _line_key(re.sub(r"^#+\s*|\*+", "", line.strip()))


def find_repeated_lines(lines: list[str]) -> set[str]:
    positions = {}
    in_code = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped or len(stripped) > MAX_ARTIFACT_LEN or _is_protected(stripped):
            continue
        key = _line_key(stripped)
        if sum(c.isalpha() for c in key) < 3:
            continue
        positions.setdefault(key, []).append(i)

    n = max(len(lines), 1)
    return {
        key for key, pos in positions.items()
        if len(pos) >= MIN_REPEATS and (pos[-1] - pos[0]) / n >= MIN_SPREAD
    }


def remove_page_artifacts(text: str) -> tuple[str, int]:
    """returns the text without running heads/page numbers and how many lines were removed"""
    if not text:
        return "", 0

    lines = text.split("\n")
    repeated = find_repeated_lines(lines)

    kept = []
    removed = 0
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        elif not in_code and (
            PAGE_NUMBER_RE.match(stripped)
            or (stripped and _line_key(stripped) in repeated)
            # headings are only dropped when the same text already repeats as a plain line
            or (stripped.startswith("#") and _heading_key(stripped) in repeated)
        ):
            removed += 1
            continue
        kept.append(line)

    return tidy_whitespace("\n".join(kept)), removed


def artifact_counts(texts) -> Counter:
    """which running heads get removed across a corpus, handy for checking the heuristic in the EDA"""
    counts = Counter()
    for text in texts:
        if text:
            counts.update(find_repeated_lines(text.split("\n")))
    return counts
