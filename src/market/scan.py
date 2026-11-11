# Market scan: what public companies are saying, in their SEC filings, about the
# technology a brief's research covers, and where that points to growth.
#
# 1. Search phrases: suggested from the question, the research summary and the
#    paper titles with simple rules (no LLM call); the consultant edits them.
# 2. Demand signals: how many filings mention each phrase in the chosen window,
#    against the same window a year earlier (counted by EDGAR, not the LLM).
# 3. Filings: the best matches, one per company, optionally only one industry;
#    from each, the sentences that mention the phrase with two either side.
# 4. One LLM call writes the scan from the research summary, the counts and the
#    excerpts, citing filings as [F1], counts as [D1] and papers by arXiv ID.
# 5. Checks (no LLM): every citation exists, every number appears in a source.
#
# Only the search phrases and an industry word ever go to SEC; never a client's
# name or project details.

import re
from datetime import date, timedelta

from src.pipeline.compress import split_sentences
from src.pipeline.pipeline import base_id, check_citations

from .edgar import FORMS

# ---------- choices offered in the UI ----------

WINDOWS = [30, 90, 180]
DEFAULT_WINDOW = 90

LENSES = {
    "client": "Client industry: where companies in the chosen industry could grow or need help",
    "firm": "Our firm: new or growing services for a professional services firm "
            "(advisory, risk and assurance, tax, audit)",
    "both": "Both: opportunities for client industries and for our firm's services",
}
DEFAULT_LENS = "both"

# SIC code ranges (inclusive) for each industry. Government agencies don't file
# with the SEC, so that one instead adds the word "government" to the search,
# finding companies that discuss government use.
INDUSTRIES = {
    "Cross-industry": None,
    "Technology": [(3570, 3579), (3660, 3679), (4810, 4899), (7370, 7379)],
    "Healthcare": [(2830, 2836), (3840, 3851), (5047, 5047), (5122, 5122), (6324, 6324), (8000, 8099)],
    "Finance": [(6000, 6411), (6700, 6769), (6771, 6799)],   # 6770 (blank-check SPACs) left out
    "Construction & Real Estate": [(1500, 1799), (6500, 6599), (6798, 6798)],
    "Government & Public Services": "government",
}
DEFAULT_INDUSTRY = "Cross-industry"

MAX_PHRASES = 4
PHRASE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-'&./]{1,58}[A-Za-z0-9.]$")

# Filings sent to the LLM, and excerpts from each
MAX_FILINGS = 8
EXCERPTS_PER_FILING = 2
EXCERPT_CHARS = 900
# Search pages read per phrase when filtering to one industry (100 filings a page)
INDUSTRY_PAGES = 3

# ---------- 1. phrase suggestions ----------

# (pattern in the research text, phrase companies use in filings), most specific
# first. The filing wording was chosen by how often it appears in EDGAR (90 days to
# Nov 2026): "algorithmic bias" 18 vs "AI bias" 1, "agentic AI" 401,
# "large language models" 218 vs singular 107, "explainable AI" 0.
PHRASE_RULES = [
    (r"retrieval[- ]augmented|\brag\b", "retrieval-augmented generation"),
    (r"\bagent(s|ic)?\b", "agentic AI"),
    (r"\bllms?\b|large language model|language models?\b", "large language models"),
    (r"generative|\bgenai\b", "generative AI"),
    (r"chatbot|conversational|virtual assistant", "chatbot"),
    (r"hallucinat", "hallucinations"),
    (r"\bbias|fairness|discriminat", "algorithmic bias"),
    (r"explainab|interpretab|transparen|responsible ai", "responsible AI"),
    (r"governance|oversight|audit(ing)? (of )?(ai|model)", "AI governance"),
    (r"model risk", "model risk management"),
    (r"\bai act\b", "EU AI Act"),
    (r"regulat|compliance", "AI regulation"),
    (r"deepfake|synthetic media", "deepfake"),
    (r"fraud", "fraud detection"),
    (r"jailbreak|adversarial|prompt injection|attack", "AI security"),
    (r"computer vision|\bimage|\bvideo", "computer vision"),
    (r"robot|embodied", "robotics"),
    (r"inference cost|compute|gpu|memory|efficien|long[- ]context", "AI infrastructure"),
    (r"machine learning", "machine learning"),
]
FALLBACK_PHRASES = ["generative AI", "artificial intelligence"]


def suggest_phrases(record, limit=MAX_PHRASES):
    """Search phrases for a brief: question first, then summary and paper titles."""
    texts = [
        record.get("query", ""),
        record.get("summary", ""),
        " ".join(s.get("title", "") for s in record.get("sources", [])),
    ]
    found = []
    for text in texts:
        lowered = text.lower()
        hits = []
        for pattern, phrase in PHRASE_RULES:
            match = re.search(pattern, lowered)
            if match and phrase not in found:
                hits.append((match.start(), phrase))
        found += [phrase for _, phrase in sorted(hits)]
    for phrase in FALLBACK_PHRASES:
        if len(found) >= 2:
            break
        if phrase not in found:
            found.append(phrase)
    return found[:limit]


def clean_phrases(phrases):
    """Validated, de-duplicated phrases; raises ValueError with a message for the page."""
    cleaned = []
    for phrase in phrases or []:
        phrase = re.sub(r"\s+", " ", str(phrase)).strip().strip('"')
        if not phrase:
            continue
        if not PHRASE_PATTERN.match(phrase):
            raise ValueError(
                f"\"{phrase}\" can't be searched. Use 3-60 letters, numbers, spaces or hyphens.")
        if phrase.lower() not in {p.lower() for p in cleaned}:
            cleaned.append(phrase)
    if not cleaned:
        raise ValueError("Add at least one search phrase.")
    if len(cleaned) > MAX_PHRASES:
        raise ValueError(f"Use at most {MAX_PHRASES} search phrases.")
    return cleaned


# ---------- 2-3. filings ----------

def useful_document(filing):
    """
    The report itself or a press release (EX-99). Contracts and merger agreements
    (EX-2, EX-10...) match because they define "artificial intelligence" in legal
    boilerplate, which says nothing about the market.
    """
    kind = (filing.get("document_type") or "").upper()
    return not kind.startswith("EX-") or kind.startswith("EX-99")


def in_industry(filing, industry):
    ranges = INDUSTRIES.get(industry)
    if not isinstance(ranges, list):
        return True
    for sic in filing.get("sics") or []:
        try:
            code = int(sic)
        except ValueError:
            continue
        if any(low <= code <= high for low, high in ranges):
            return True
    return False


def edgar_query(phrase, industry):
    extra = INDUSTRIES.get(industry)
    return f'"{phrase}"' + (f" {extra}" if isinstance(extra, str) else "")


def demand_signals(edgar, phrases, industry, since, until):
    """Filings mentioning each phrase now vs. the same window a year earlier."""
    year = timedelta(days=365)
    signals = []
    for number, phrase in enumerate(phrases, start=1):
        query = edgar_query(phrase, industry)
        recent = edgar.count(query, since, until)
        earlier = edgar.count(query, since - year, until - year)
        signals.append({
            "id": f"D{number}",
            "phrase": phrase,
            "recent": recent,
            "year_earlier": earlier,
            "change": None if not earlier else round((recent - earlier) / earlier * 100),
        })
    return signals


def collect_filings(edgar, phrases, industry, since, until, max_filings=MAX_FILINGS):
    """
    The best matching filings across the phrases, one per company, taking turns
    between phrases so each phrase gets filings. Also returns how many companies
    in the industry were found, for the page.
    """
    by_phrase = []
    for phrase in phrases:
        query = edgar_query(phrase, industry)
        # an industry filter, and dropping contracts, both thin out a page
        pages = INDUSTRY_PAGES if isinstance(INDUSTRIES.get(industry), list) else 2
        matches = []
        for page in range(pages):
            result = edgar.search(query, since, until, page=page)
            matches += [f for f in result["filings"]
                        if useful_document(f) and in_industry(f, industry)]
            if len(matches) >= max_filings or (page + 1) * 100 >= result["total"]:
                break
        by_phrase.append((phrase, matches))

    chosen = []
    companies = set()
    active = [(phrase, iter(matches)) for phrase, matches in by_phrase]
    while active and len(chosen) < max_filings:
        for entry in list(active):
            phrase, matches = entry
            filing = next((f for f in matches if f["cik"] not in companies), None)
            if filing is None:
                active.remove(entry)
                continue
            companies.add(filing["cik"])
            chosen.append({**filing, "phrase": phrase})
            if len(chosen) >= max_filings:
                break
    return chosen


def phrase_regex(phrase):
    words = [re.escape(w) for w in re.split(r"[\s\-]+", phrase) if w]
    return re.compile(r"\b" + r"[\s\-]+".join(words) + r"\w*", re.IGNORECASE)


def excerpts(text, phrase, limit=EXCERPTS_PER_FILING, neighbors=2, max_chars=EXCERPT_CHARS):
    """
    Passages around the first mentions of phrase: the sentence with it and up to
    two sentences either side, cut to max_chars around the mention.
    """
    pattern = phrase_regex(phrase)
    found = []
    skip_until = -1
    for match in pattern.finditer(text):
        if len(found) >= limit:
            break
        # a later mention inside the passage just taken would repeat it
        if match.start() < skip_until:
            continue
        # split around this mention, so an earlier mention in reach isn't picked instead
        before = split_sentences(text[max(0, match.start() - 2500):match.start()])
        after = split_sentences(text[match.start():match.end() + 2500])
        if not after:
            continue
        mid_sentence = before and not re.search(r"[.!?][\"”)]?\s*$", text[max(0, match.start() - 3):match.start()])
        current = (before.pop() + " " if mid_sentence else "") + after[0]
        passage = " ".join(before[-neighbors:] + [current] + after[1:neighbors + 1]) if neighbors else current
        if len(passage) > max_chars:
            at = pattern.search(passage).start()
            left = max(0, at - max_chars // 2)
            passage = ("..." if left else "") + passage[left:left + max_chars].strip() + "..."
        # filings often open with their file name, e.g. "ea0306372ex99-1.htm PRESS RELEASE"
        passage = re.sub(r"^\S+\.(?:htm|html|txt)\s+", "", re.sub(r"\s+", " ", passage).strip())
        skip_until = match.end() + max_chars
        # a title repeated in the body gives the same passage twice
        if any(_overlap(passage, earlier) for earlier in found):
            continue
        found.append(passage)
    return found


def _overlap(a, b):
    """True when two passages share most of their words."""
    words_a, words_b = set(a.lower().split()), set(b.lower().split())
    return len(words_a & words_b) > 0.6 * min(len(words_a), len(words_b))


def gather(edgar, phrases, industry, window_days, today=None):
    """Everything the LLM step needs from EDGAR. Raises EdgarError if EDGAR fails."""
    until = today or date.today()
    since = until - timedelta(days=window_days)

    signals = demand_signals(edgar, phrases, industry, since, until)
    filings = []
    for filing in collect_filings(edgar, phrases, industry, since, until):
        quotes = excerpts(edgar.document_text(filing), filing["phrase"])
        if quotes:
            filings.append({**filing, "excerpts": quotes})
    for number, filing in enumerate(filings, start=1):
        filing["id"] = f"F{number}"

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "forms": FORMS,
        "signals": signals,
        "filings": filings,
    }


# ---------- 5. checks ----------

# Words that don't identify a company on their own
COMPANY_WORDS = {
    "inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc", "lp", "group",
    "holdings", "holding", "international", "technologies", "technology", "financial", "bancorp",
    "the", "and", "of", "sa", "nv", "ag", "trust", "partners",
}


def _section(text, heading):
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def _names_company(text, filing):
    """Whether text names the filing's company, by ticker or by its distinctive first word."""
    if filing.get("ticker") and len(filing["ticker"]) >= 2 and re.search(
            rf"\b{re.escape(filing['ticker'])}\b", text):
        return True
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z&'\-]+", filing["company"]) if w.lower() not in COMPANY_WORDS]
    return bool(words) and len(words[0]) >= 3 and re.search(rf"\b{re.escape(words[0])}\b", text, re.IGNORECASE) is not None


SOURCE_CITE = re.compile(r"\[((?:[FD]\d+)(?:\s*[,;]\s*[FD]\d+)*)\]")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?")


def _numbers(text):
    return {n.rstrip(".,") for n in NUMBER.findall(text) if len(n.rstrip("%")) > 1 or "%" in n}


def check_scan(text, gathered, record):
    """Citations that point nowhere, and numbers that appear in no source."""
    filing_ids = {f["id"] for f in gathered["filings"]}
    signal_ids = {s["id"] for s in gathered["signals"]}
    cited = []
    for group in SOURCE_CITE.findall(text):
        for cite in re.split(r"\s*[,;]\s*", group):
            if cite not in cited:
                cited.append(cite)
    unknown = [c for c in cited if c not in filing_ids | signal_ids]

    papers = check_citations(text, record.get("sources", []))
    summary_cited = {base_id(p) for p in record.get("citation_check", {}).get("cited", [])}
    papers_not_in_summary = [p for p in papers["cited"] if p not in summary_cited]

    source_text = " ".join([
        record.get("summary", ""),
        " ".join(" ".join(f["excerpts"]) + f" {f['filed']} {f['form']}" for f in gathered["filings"]),
        " ".join(f"{s['recent']} {s['year_earlier']} {s['change']} {s['change']}% +{s['change']}%"
                 for s in gathered["signals"]),
        f"{gathered['since']} {gathered['until']}",
    ])
    sources_numbers = _numbers(source_text)
    # paper IDs are checked above; window lengths may be quoted too
    allowed = {p for p in papers["cited"]} | {str(len(gathered["filings"]))}
    ungrounded = sorted(
        n for n in _numbers(SOURCE_CITE.sub("", text))
        if n not in sources_numbers and n not in allowed and not re.match(r"^\d{4}\.\d{4,5}", n)
    )

    from src.translation.market_prompts import MARKET_SECTIONS

    # who each opportunity is "For:" (naming a company as evidence in "Why now" is fine)
    targets = " ".join(re.findall(r"For:\s*(.*?)(?:\.\s+Why now:|$)",
                                  _section(text, "Growth Opportunities"), re.MULTILINE))
    named = [f["company"] for f in gathered["filings"] if _names_company(targets, f)]

    headings = [h.strip() for h in re.findall(r"^## (.+)$", text, re.MULTILINE)]
    dates = sorted(f["filed"] for f in gathered["filings"] if f["filed"])

    return {
        "citations": {
            "ok": not unknown and not papers["cited_not_retrieved"] and not papers_not_in_summary,
            "cited_sources": cited,
            "unknown_sources": unknown,
            "papers_not_retrieved": papers["cited_not_retrieved"],
            "papers_not_in_summary": papers_not_in_summary,
        },
        "numbers": {"ok": not ungrounded, "ungrounded": ungrounded},
        # companies from the filings named as who an opportunity is for: evidence, not targets
        "targets": {"ok": not named, "named": named},
        "template": {"ok": headings == MARKET_SECTIONS, "missing": [h for h in MARKET_SECTIONS if h not in headings]},
        "sources": {
            "filings": len(gathered["filings"]),
            "companies": len({f["cik"] for f in gathered["filings"]}),
            "first_filed": dates[0] if dates else None,
            "last_filed": dates[-1] if dates else None,
            "thin": len(gathered["filings"]) < 3,
        },
    }
