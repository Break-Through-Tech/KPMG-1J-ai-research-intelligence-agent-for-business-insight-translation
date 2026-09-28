# character and markup level cleanup of the markdown that pymupdf4llm produces
# nothing here looks at document structure, that happens in boilerplate.py and sections.py

import re
import unicodedata

# picture blocks, in case ingestion's clean_text didn't run, plus the placeholder it leaves behind
PICTURE_BLOCK_RE = re.compile(r"<!-- Start of picture text -->.*?<!-- End of picture text -->", re.DOTALL)
PICTURE_PLACEHOLDER_RE = re.compile(r"\[Picture Omitted\]|\*\*==> picture \[.*?\] intentionally omitted <==\*\*")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# control characters (keeps \t and \n), zero width characters, soft hyphens and the unicode replacement char
JUNK_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200d\u2060\ufeff\ufffd]")

SUP_RE = re.compile(r"<sup>(.*?)</sup>", re.DOTALL)
SUB_RE = re.compile(r"<sub>(.*?)</sub>", re.DOTALL)
BR_RE = re.compile(r"<br\s*/?>", re.I)
SIMPLE_TAG_RE = re.compile(r"</?(?:b|i|u|em|strong|span|sup|sub)\b[^>]*>", re.I)
FOOTNOTE_MARK_RE = re.compile(r"^[\d\s,*†‡§¶∗⋆♠♣♥♦#]+$")

# pymupdf4llm wraps italic spans in underscores, which splits numbers apart: "2 _._ 23" -> "2.23"
SPLIT_DECIMAL_RE = re.compile(r"(\d)\s*_\s*\.\s*_\s*(\d)")
ITALIC_RE = re.compile(r"(?<![\w_])_(?=\S)([^_\n]+?)(?<=\S)_(?![\w_])")
BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
# pymupdf4llm sometimes opens bold in one table cell and closes it in another, leaving orphans
ORPHAN_BOLD_RE = re.compile(r"\*\*")

MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.M)
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

LATEX_ESCAPE_RE = re.compile(r"\\([&%_#$])")  # "S\&P", "34\%"
LATEX_CMD_RE = re.compile(r"\\(?:textit|textbf|emph|texttt|textrm|mathrm|mathbf|mathcal|text)\{([^{}]*)\}")


def _replace_sup(match):
    # footnote markers after a word or punctuation get dropped, exponents like x^2 or 10^-3 are kept
    content = match.group(1).replace("*", "").strip()
    before = match.string[max(0, match.start() - 2):match.start()]
    is_exponent = bool(re.search(r"(?:^|[^A-Za-z0-9])[A-Za-z]$|\d$", before))
    if is_exponent and content:
        return "^" + content
    if not content or FOOTNOTE_MARK_RE.match(content):
        return ""
    return "^" + content


def strip_markup(text: str) -> str:
    text = PICTURE_BLOCK_RE.sub("", text)
    text = PICTURE_PLACEHOLDER_RE.sub("", text)
    text = HTML_COMMENT_RE.sub("", text)
    text = BR_RE.sub(" ", text)
    text = SUP_RE.sub(_replace_sup, text)
    text = SUB_RE.sub(lambda m: "_" + m.group(1).strip(), text)
    text = SIMPLE_TAG_RE.sub("", text)
    text = SPLIT_DECIMAL_RE.sub(r"\1.\2", text)
    text = ITALIC_RE.sub(r"\1", text)
    text = BOLD_RE.sub(r"\1", text)
    text = ORPHAN_BOLD_RE.sub("", text)
    return text


def tidy_whitespace(text: str) -> str:
    text = MULTI_SPACE_RE.sub(" ", text)
    text = TRAILING_SPACE_RE.sub("", text)
    text = MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def normalize_text(text: str | None) -> str:
    if not text:
        return ""
    # NFKC folds ligatures (ﬁ -> fi), math italic letters (𝑝 -> p) and full width characters
    text = unicodedata.normalize("NFKC", text)
    text = JUNK_CHARS_RE.sub("", text)
    text = strip_markup(text)
    return tidy_whitespace(text)


# abstracts come from the arxiv API, not the PDF, so they only need light cleanup
def normalize_abstract(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = JUNK_CHARS_RE.sub("", text)
    text = LATEX_CMD_RE.sub(r"\1", text)
    text = LATEX_ESCAPE_RE.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip()
