# splits section rows into retrieval chunks with metadata
# input is chunk_input.jsonl from Abdullah's prepare_for_chunking.py: one row per kept section,
# already cleaned (src/preprocessing) and already filtered (no references, appendix, front matter)
#
# baseline strategy:
#   - every section row is chunked on its own, so a chunk never spans two sections
#     and always has one section label to cite
#   - sections under min_section_tokens are merged into the next section of the same paper
#   - inside a section: fixed-size windows with overlap, packed from whole sentences,
#     so a sentence is only ever split if it is longer than a whole chunk (big tables)
#   - title + section heading are prepended to the text we embed, but not to the stored text

import re
from dataclasses import dataclass

# same rule of thumb preprocessing uses for est_tokens, so the numbers line up
CHARS_PER_TOKEN = 4


def count_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN)) if text else 0


@dataclass
class ChunkConfig:
    chunk_tokens: int = 512        # max size of a chunk
    overlap_tokens: int = 64       # how much of the end of one chunk is repeated at the start of the next
    min_section_tokens: int = 30   # sections shorter than this are merged into the next section


# ---------- sentences ----------

# words that end in a period without ending the sentence
_ABBREVIATIONS = ("e.g", "i.e", "et al", "etc", "vs", "fig", "figs", "eq", "eqs", "sec", "tab",
                  "no", "approx", "cf", "resp", "al", "dr", "mr", "ms", "prof")
_ABBREV_RE = re.compile(r"(?:\b(?:" + "|".join(re.escape(a) for a in _ABBREVIATIONS) + r")|\b[A-Z])\.$", re.I)
_SENT_END_RE = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9\"'(\[])")


def split_sentences(text: str) -> list[str]:
    """splits on sentence ends, keeping table rows, list items and lines that look like
    structure (markdown tables, bullets, captions) as their own units"""
    units = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        # a markdown table or a list is kept line by line, never merged into prose
        if all(l.strip().startswith(("|", "-", "*", "•")) or re.match(r"^\s*\d+[.)]\s", l) for l in lines):
            units.extend(l.strip() for l in lines if l.strip())
            continue
        prose = " ".join(l.strip() for l in lines)
        start = 0
        for m in _SENT_END_RE.finditer(prose):
            candidate = prose[start:m.start()].rstrip()
            if _ABBREV_RE.search(candidate) or re.search(r"\d\.$", candidate[-3:]) and m.end() < len(prose) and prose[m.end()].isdigit():
                continue  # "Fig. 3", "et al. found", "3. 5"
            units.append(prose[start:m.end()].strip())
            start = m.end()
        if prose[start:].strip():
            units.append(prose[start:].strip())
    return units


def _hard_split(sentence: str, max_tokens: int) -> list[str]:
    """last resort for a single unit bigger than a chunk: split on words"""
    words, parts, current = sentence.split(), [], []
    for w in words:
        if current and count_tokens(" ".join(current + [w])) > max_tokens:
            parts.append(" ".join(current))
            current = []
        current.append(w)
    if current:
        parts.append(" ".join(current))
    return parts


# ---------- windows ----------

def window_text(text: str, cfg: ChunkConfig) -> list[str]:
    """packs sentences into chunks of at most cfg.chunk_tokens, repeating roughly
    cfg.overlap_tokens worth of whole sentences between neighbouring chunks"""
    units = []
    for s in split_sentences(text):
        units.extend(_hard_split(s, cfg.chunk_tokens) if count_tokens(s) > cfg.chunk_tokens else [s])

    chunks, current = [], []
    for unit in units:
        if current and count_tokens(" ".join(current + [unit])) > cfg.chunk_tokens:
            chunks.append(" ".join(current))
            # carry the last sentences forward as overlap, without letting overlap + next unit overflow
            overlap = []
            for prev in reversed(current):
                if count_tokens(" ".join([prev] + overlap)) > cfg.overlap_tokens:
                    break
                overlap.insert(0, prev)
            while overlap and count_tokens(" ".join(overlap + [unit])) > cfg.chunk_tokens:
                overlap.pop(0)
            current = overlap
        current.append(unit)
    if current:
        chunks.append(" ".join(current))
    return chunks


# ---------- sections -> chunks ----------

def merge_short_sections(rows: list[dict], cfg: ChunkConfig) -> list[dict]:
    """rows are one paper's sections in reading order. A section under cfg.min_section_tokens
    (often a heading with one sentence) is merged into the next section, keeping the next
    section's label. A short last section joins the one before it."""
    merged, carry = [], None
    for r in rows:
        r = dict(r)
        if carry:
            r["text"] = f"{carry['text']}\n\n{r['text']}"
            r["merged_from"] = carry.get("merged_from", []) + [carry["section"] or "(no section)"]
            carry = None
        if count_tokens(r["text"]) < cfg.min_section_tokens:
            carry = r
            continue
        merged.append(r)
    if carry:
        if merged:
            merged[-1]["text"] += f"\n\n{carry['text']}"
            merged[-1]["merged_from"] = merged[-1].get("merged_from", []) + [carry["section"] or "(no section)"]
        else:
            merged.append(carry)
    return merged


def chunk_paper(rows: list[dict], cfg: ChunkConfig = ChunkConfig()) -> list[dict]:
    """one paper's section rows (from chunk_input.jsonl, in order) -> list of chunk dicts"""
    rows = [r for r in rows if (r.get("text") or "").strip()]
    if not rows:
        return []
    first = rows[0]
    meta = {
        "paper_id": first["paper_id"],
        "title": first["title"],
        "authors": [str(a) for a in first["authors"]],
        "arxiv_url": first["arxiv_url"],
    }

    pieces = []  # (section row, chunk text)
    for r in merge_short_sections(rows, cfg):
        for text in window_text(r["text"], cfg):
            pieces.append((r, text))

    chunks = []
    for i, (r, text) in enumerate(pieces):
        section = r["section"] or "(no section)"
        chunks.append({
            "chunk_id": f"{meta['paper_id']}::{i:04d}",
            **meta,
            "section": section,
            "section_type": r["section_type"],
            "section_id": r["section_id"],
            "source": r.get("source", ""),
            "chunk_index": i,
            "n_chunks_in_paper": len(pieces),
            "text": text,
            # what gets embedded: the title and section give the chunk context it lacks on its own
            "text_for_embedding": f"{meta['title']}\nSection: {section}\n\n{text}",
            "n_tokens": count_tokens(text),
        })
    return chunks
