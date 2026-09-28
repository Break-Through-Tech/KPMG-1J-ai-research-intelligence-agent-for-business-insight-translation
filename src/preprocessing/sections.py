# splits cleaned paper text into sections using the markdown headings pymupdf4llm emits
# and labels each section with a coarse type so later steps can drop references/appendix
# or carry a section label into citations

import re

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# some PDFs render the references title as a bold line instead of a heading
PSEUDO_REF_HEADING_RE = re.compile(r"^\**\s*(?:\d+\.?\s*)?(references|bibliography)\s*\**$", re.I)
# "3", "3.2", "3.2.", "A", "B.1", "IV." at the start of a heading
NUMBERING_RE = re.compile(r"^((?:\d+|[A-Z]|[IVX]+)(?:\.\d+)*\.?)\s+(.+)$")

# the references title has to match exactly, "Reference-free evaluation" is not a bibliography
REFERENCES_TITLE_RE = re.compile(r"^(?:references?|bibliography|references and notes|literature cited)$", re.I)

# checked in order, first match wins
SECTION_KEYWORDS = [
    ("acknowledgments", ("acknowledg",)),
    ("appendix", ("appendix", "appendices", "supplementary", "supplemental")),
    ("abstract", ("abstract",)),
    ("limitations", ("limitation",)),
    ("conclusion", ("conclusion", "concluding", "summary and future", "closing remarks")),
    ("back_matter", ("credit authorship", "author contribution", "declaration of", "competing interest",
                     "conflict of interest", "conflicts of interest", "data availability", "code availability",
                     "funding", "reproducibility statement", "use of large language models", "llm usage",
                     "ai use statement", "use of ai", "use of generative ai")),
    ("introduction", ("introduction", "motivation")),
    ("related_work", ("related work", "background", "preliminar", "prior work", "literature")),
    ("discussion", ("discussion", "implication", "broader impact", "ethic", "future work", "future direction")),
    ("results", ("result", "analysis", "ablation", "finding", "comparison", "case stud")),
    ("experiments", ("experiment", "evaluation", "setup", "benchmark", "dataset", "implementation detail")),
    ("method", ("method", "approach", "framework", "architecture", "model", "algorithm",
                "formulation", "proposed", "design", "system", "pipeline")),
]

# types left out of body_text: they either duplicate metadata or are noise for retrieval
EXCLUDED_FROM_BODY = {"front_matter", "acknowledgments", "back_matter", "references", "appendix"}
# once one of these appears the main text has started
BODY_START_TYPES = {"abstract", "introduction"}
# only look for the abstract/introduction among the first few headings, an "introduction" deep in an appendix doesn't count
BODY_START_WINDOW = 12
# sub-headings with these types keep them instead of inheriting their parent's ("5.2 Limitations" under "5 Discussion")
STANDALONE_TYPES = {"references", "acknowledgments", "back_matter", "appendix", "limitations", "conclusion"}
# a heading like this starts the appendix even when it comes before the references
APPENDIX_START_RE = re.compile(r"^(?:appendix|appendices|supplementary|supplemental)\b", re.I)
# the title/author block and the abstract never have real sub-sections, so nothing inherits from them
NON_PARENT_TYPES = {"front_matter", "abstract", "other"}


def clean_heading(raw: str) -> tuple[str, str]:
    """'**3.2 Threat Model**' -> ('3.2', 'Threat Model')"""
    heading = re.sub(r"[*_`]", "", raw).strip().rstrip(":").strip()
    match = NUMBERING_RE.match(heading)
    if match:
        return match.group(1).rstrip("."), match.group(2).strip()
    return "", heading


def classify_heading(title: str) -> str:
    if REFERENCES_TITLE_RE.match(title):
        return "references"
    lowered = title.lower()
    for section_type, keywords in SECTION_KEYWORDS:
        if any(lowered.startswith(k) or f" {k}" in f" {lowered}" for k in keywords):
            return section_type
    return "other"


def _parse_headings(text: str) -> list[tuple[int, int, str]]:
    """(line index, level, raw heading) for every heading line, skipping code blocks"""
    found = []
    in_code = False
    for i, line in enumerate(text.split("\n")):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = HEADING_RE.match(stripped)
        if match:
            found.append((i, len(match.group(1)), match.group(2)))
        elif PSEUDO_REF_HEADING_RE.match(stripped):
            found.append((i, 2, stripped))
    return found


def split_sections(text: str) -> list[dict]:
    if not text:
        return []

    lines = text.split("\n")
    headings = _parse_headings(text)

    sections = []
    # anything before the first heading (title block, authors, affiliations)
    first_line = headings[0][0] if headings else len(lines)
    preamble = "\n".join(lines[:first_line]).strip()
    if preamble:
        sections.append({"level": 0, "number": "", "heading": "", "section_type": "front_matter", "text": preamble})

    for n, (line_idx, level, raw) in enumerate(headings):
        end = headings[n + 1][0] if n + 1 < len(headings) else len(lines)
        number, title = clean_heading(raw)
        sections.append({
            "level": level,
            "number": number,
            "heading": title,
            "section_type": classify_heading(title),
            "text": "\n".join(lines[line_idx + 1:end]).strip(),
        })

    _assign_types(sections)

    for idx, section in enumerate(sections):
        section["idx"] = idx
        section["char_count"] = len(section["text"])
    return sections


def _assign_types(sections: list[dict]) -> None:
    """fixes up the per-heading keyword guesses using document position and nesting"""
    # the main text starts at the abstract/introduction, if one shows up near the top of the paper
    body_start = next((i for i, s in enumerate(sections[:BODY_START_WINDOW])
                       if s["section_type"] in BODY_START_TYPES), None)
    seen_references = False
    seen_appendix = False
    seen_conclusion = False
    stack = []          # (level, section_type) of the enclosing headings
    by_number = {}      # "4" -> section_type, so "4.1" can find its parent

    for i, section in enumerate(sections):
        own_type = section["section_type"]
        level = section["level"]
        number = section["number"]
        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_type = _parent_type(number, by_number, stack)

        if level == 0 or (body_start is not None and i < body_start):
            # preamble, title heading and author block before the abstract/introduction
            section_type = "front_matter"
        elif own_type == "references":
            section_type = "references"
            seen_references = True
        elif own_type in ("acknowledgments", "back_matter"):
            section_type = own_type
        elif seen_references or seen_appendix or parent_type == "appendix":
            # everything after the bibliography or an "Appendix" heading is appendix material
            section_type = "appendix"
        elif seen_conclusion and re.fullmatch(r"[A-Z](?:\.\d+)*", number):
            # lettered sections after the conclusion ("A Proofs", "B.1 Hyperparameters")
            section_type = "appendix"
        elif own_type in STANDALONE_TYPES or parent_type is None:
            section_type = own_type
        elif "." in number:
            # numbered sub-sections follow their parent: "4.3 RQ2 Design Quality" under "4 Results" is results
            section_type = parent_type
        elif not number and own_type == "other":
            # unnumbered sub-headings like "Attraction prompt" take the enclosing section's type
            section_type = parent_type
        else:
            section_type = own_type

        if number == "A" and section_type != "appendix":
            # "A Survey of ..." is an article, not appendix A
            section["heading"] = f"A {section['heading']}"
            section["number"] = number = ""

        if section_type in ("conclusion", "limitations"):
            seen_conclusion = True
        if section_type == "appendix" and APPENDIX_START_RE.match(section["heading"]):
            seen_appendix = True
        section["section_type"] = section_type
        if level > 0:
            stack.append((level, section_type))
        if number:
            by_number[number] = section_type


def _parent_type(number: str, by_number: dict, stack: list) -> str | None:
    """type of the enclosing section, None if there is no meaningful parent"""
    if "." in number:
        parent = by_number.get(number.rsplit(".", 1)[0])
        if parent:
            return None if parent in NON_PARENT_TYPES else parent
    # otherwise the nearest enclosing heading
    for _, section_type in reversed(stack):
        if section_type not in ("front_matter", "abstract"):
            return None if section_type == "other" else section_type
    return None


def build_body_text(sections: list[dict]) -> str:
    """the retrieval ready text: main sections only, headings kept as markdown for the chunker"""
    parts = []
    for section in sections:
        if section["section_type"] in EXCLUDED_FROM_BODY:
            continue
        heading = " ".join(p for p in (section["number"], section["heading"]) if p)
        if heading:
            parts.append(f"{'#' * max(section['level'], 1)} {heading}")
        if section["text"]:
            parts.append(section["text"])
    return "\n\n".join(parts)
