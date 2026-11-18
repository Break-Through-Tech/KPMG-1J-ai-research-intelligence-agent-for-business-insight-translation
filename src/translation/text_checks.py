# Reading the Markdown the LLM writes back: its "## " headings, the text under one
# heading, and the numbers it states. Shared by the brief checks (src/app/checks.py),
# the market scan checks (src/market/scan.py) and the slide checks (src/app/present.py).

import re

# 12, 3.5, 1,200 or 40% (a lone digit is ignored, it's usually a list number)
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?")


def headings(text):
    """The '## heading' lines of text, in order."""
    return [h.strip() for h in re.findall(r"^## (.+)$", text, re.MULTILINE)]


def section_text(text, heading):
    """Text under one '## heading', or '' if it is missing."""
    match = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def numbers_in(text):
    """The numbers stated in text, without trailing punctuation."""
    return {n.rstrip(".,") for n in NUMBER.findall(text) if len(n.rstrip("%")) > 1 or "%" in n}
