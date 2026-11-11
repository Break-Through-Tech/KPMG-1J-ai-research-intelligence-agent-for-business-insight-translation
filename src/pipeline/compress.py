# Shrinks the paper text sent to the summarization LLM without dropping what the
# summary needs (findings, numbers, limitations). Runs between retrieval and
# format_retrieved_content, and never calls an LLM. Off unless --compress is
# given: in testing (src/pipeline/README.md) it cut the prompt 4% but the model
# reasoned longer, so answers were slower.
#
# 1. Remove repeated text: the overlap between neighbouring chunks of the same
#    section, and passage sentences that repeat the abstract or an earlier passage.
# 2. Clean each passage: citation markers ("[12]", "(Smith et al., 2025)"), URLs,
#    LaTeX commands and markdown noise. Numbers and tables are kept.
# 3. Keep the sentences that matter: the ones closest to the question, with two
#    sentences either side for context, plus every sentence with a number or a
#    caveat ("however", "only", "fails", "limitation"...). Gaps are marked [...]
#    so the LLM doesn't join statements across them.
# 4. Budget by rank (8,000 tokens by default): titles and abstracts always go in; then every paper's best
#    chunk, then limitations passages, then results passages, higher-ranked
#    papers first, until the token budget is used. A results passage comes last
#    when the paper's best chunk is already from its results.
#
# Token counts are estimates (about 4 characters a token), close enough to
# budget with; the exact counts come back from the LLM API.

import math
import re
from dataclasses import dataclass

import numpy as np

GAP = " [...] "

# ---------- 2. cleanup ----------

NUMERIC_CITATION = re.compile(r"\s?\[\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\]")
_AUTHOR = r"[A-Z][A-Za-z'’\-]+(?: et al\.?| and [A-Z][A-Za-z'’\-]+| & [A-Z][A-Za-z'’\-]+)?"
_YEAR = r"(?:19|20)\d{2}[a-z]?"
AUTHOR_YEAR_CITATION = re.compile(
    rf"\s?\((?:see |e\.g\.,? |cf\. )?{_AUTHOR},? {_YEAR}(?:[;,] ?(?:{_AUTHOR},? )?{_YEAR})*\)"
)
# "Smith et al. (2025) show" -> "Smith et al. show"
NARRATIVE_YEAR = re.compile(rf"(et al\.?)\s?\({_YEAR}\)")
URL = re.compile(r"\(?https?://[^\s)]+\)?")
LATEX_DROP = re.compile(r"\\(?:cite[tp]?|ref|label|eqref|footnote)\{[^}]*\}")
LATEX_KEEP = re.compile(r"\\(?:textbf|textit|emph|texttt|mathrm|text)\{([^}]*)\}")
TABLE_UNDERSCORE = re.compile(r"(?<=\d)_|_(?=[\d±])")


def clean_text(text):
    """Remove citation markers, URLs, LaTeX commands and markdown noise; keep the facts."""
    text = str(text or "")
    text = LATEX_DROP.sub("", text)
    text = LATEX_KEEP.sub(r"\1", text)
    text = NUMERIC_CITATION.sub("", text)
    text = AUTHOR_YEAR_CITATION.sub("", text)
    text = NARRATIVE_YEAR.sub(r"\1", text)
    text = URL.sub("", text)
    text = text.replace("**", "")
    text = TABLE_UNDERSCORE.sub("", text)
    text = re.sub(r"\|{2,}", "|", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([,.;:])", r"\1", text)
    return text.strip()


# ---------- sentences ----------

# Words that end in a period without ending the sentence
ABBREVIATIONS = {
    "e.g", "i.e", "al", "fig", "figs", "eq", "eqs", "vs", "approx", "sec", "secs",
    "tab", "no", "resp", "cf", "etc", "ref", "refs", "appx", "app", "ch", "dr", "mr", "ms",
}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"“])|\n+")


def split_sentences(text):
    parts = [p.strip() for p in SENTENCE_END.split(text) if p and p.strip()]
    sentences = []
    for part in parts:
        if sentences:
            last_word = sentences[-1].rsplit(" ", 1)[-1].rstrip(".").lower()
            # "et al." or "Fig." or a single initial: the sentence goes on
            if last_word in ABBREVIATIONS or (len(last_word) == 1 and last_word.isalpha()):
                sentences[-1] += " " + part
                continue
        sentences.append(part)
    return sentences


def _normalized(sentence):
    return re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()


def approx_tokens(text):
    return math.ceil(len(text or "") / 4)


# ---------- 3. which sentences to keep ----------

HAS_NUMBER = re.compile(r"\d")
CAVEAT = re.compile(
    r"\b(?:limit\w*|however|although|but|fail\w*|only|cannot|can't|does not|do not|did not|"
    r"may not|unclear|restrict\w*|caveat\w*|future work|weak\w*|drawback\w*|"
    r"not (?:yet|always|guarantee\w*)|degrad\w*|worse)\b",
    re.IGNORECASE,
)
WORD = re.compile(r"[a-z0-9][a-z0-9\-]+")
STOP = {
    "the", "and", "for", "are", "with", "that", "this", "from", "how", "what", "can",
    "does", "their", "they", "into", "when", "which", "about", "should", "could", "would",
}


def lexical_scores(query, sentences):
    """Share of the question's words found in each sentence (used when there's no embedder)."""
    words = {w for w in WORD.findall(query.lower()) if w not in STOP}
    if not words:
        return np.zeros(len(sentences))
    return np.array([len(words & set(WORD.findall(s.lower()))) / len(words) for s in sentences])


@dataclass
class CompressSettings:
    # Paper text for the summary prompt, titles and abstracts included. On the 24
    # benchmark questions (evaluation/compare_context.py) 8,000 trims only the
    # longest questions: 7,913 -> 7,352 tokens on average, 90% of numbers and 95%
    # of caveat sentences kept, no limitations passage dropped. 5,000 saved 39%
    # but dropped most limitations and results passages (31% of numbers kept).
    budget_tokens: int = 8000
    # Sentences of context kept before and after each sentence close to the question
    neighbors: int = 2
    # ... and before and after each sentence kept for a number or caveat
    must_keep_neighbors: int = 1
    # Share of a passage's sentences picked for closeness to the question (at least 2)
    top_share: float = 0.25
    # Passages this short (estimated tokens) are sent whole
    min_tokens_to_trim: int = 120
    # If trimming would keep more than this share of a passage, send it whole
    keep_whole_above: float = 0.85


def select_sentences(sentences, scores, settings):
    """Indexes of the sentences to keep, in order."""
    n = len(sentences)
    keep = set()

    top = max(2, round(n * settings.top_share))
    for i in np.argsort(-np.asarray(scores), kind="stable")[:top]:
        keep.update(range(i - settings.neighbors, i + settings.neighbors + 1))

    for i, sentence in enumerate(sentences):
        if HAS_NUMBER.search(sentence) or CAVEAT.search(sentence):
            keep.update(range(i - settings.must_keep_neighbors, i + settings.must_keep_neighbors + 1))

    return sorted(i for i in keep if 0 <= i < n)


def join_kept(sentences, kept):
    """Kept sentences joined, with [...] wherever sentences were left out."""
    if not kept:
        return ""
    text = "" if kept[0] == 0 else GAP.strip() + " "
    for position, i in enumerate(kept):
        if position and i != kept[position - 1] + 1:
            text += GAP
        elif position:
            text += " "
        text += sentences[i]
    if kept[-1] != len(sentences) - 1:
        text += " " + GAP.strip()
    return text


# ---------- 1. overlap between neighbouring chunks ----------

def chunk_index(chunk_id):
    match = re.search(r"::(\d+)$", str(chunk_id or ""))
    return int(match.group(1)) if match else None


def strip_overlap(earlier, later, longest=800, shortest=20):
    """later without its opening, if that opening repeats the end of earlier."""
    for length in range(min(len(earlier), len(later), longest), shortest - 1, -1):
        if earlier[-length:] == later[:length]:
            return later[length:].lstrip()
    return later


# ---------- the compressor ----------

RESULT_TYPES = {"results", "experiments"}


class ContextCompressor:
    """
    compress(query, papers) -> (papers, stats). The papers are copies with shorter
    best_chunk_text and passages; passages that didn't fit the budget are left
    out. stats says how much was cut and what was dropped, and is saved with the answer.

    embedder: a TextEmbedder (the retriever's); without one, sentences are ranked
              by the words they share with the question.
    """

    def __init__(self, embedder=None, settings=None):
        self.embedder = embedder
        self.settings = settings or CompressSettings()

    # pieces are the non-abstract texts of one paper: its best chunk and its passages
    def _pieces(self, rank, paper):
        pieces = [{
            "rank": rank, "kind": "main", "chunk_id": paper.get("chunk_id", ""),
            "section": paper.get("best_chunk_section", ""),
            "section_type": paper.get("best_chunk_section_type") or "",
            "text": str(paper.get("best_chunk_text") or ""),
        }]
        for passage in paper.get("passages") or []:
            pieces.append({
                "rank": rank, "kind": passage.get("label") or "passage",
                "chunk_id": passage.get("chunk_id", ""), "section": passage.get("section", ""),
                "section_type": passage.get("section_type") or "", "text": str(passage.get("text") or ""),
                "passage": passage,
            })
        return pieces

    def _remove_overlaps(self, pieces):
        """Step 1a: neighbouring chunks of one section share ~200 characters; keep them once."""
        by_index = {chunk_index(p["chunk_id"]): p for p in pieces if chunk_index(p["chunk_id"]) is not None}
        for index, piece in by_index.items():
            before = by_index.get(index - 1)
            if before is not None and before["section"] == piece["section"]:
                piece["text"] = strip_overlap(before["text"], piece["text"])

    def _scores(self, query, sentences):
        if not sentences:
            return np.zeros(0)
        if self.embedder is None:
            return lexical_scores(query, sentences)
        query_vector = self.embedder.embed_query(query)
        vectors = self.embedder.model.encode(
            sentences, batch_size=64, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False,
        )
        return vectors @ query_vector

    def compress(self, query, papers):
        settings = self.settings
        papers = [dict(paper) for paper in papers]
        all_pieces = []

        for rank, paper in enumerate(papers):
            pieces = self._pieces(rank, paper)
            self._remove_overlaps(pieces)

            # Step 1b + 2: clean, split, and drop sentences already said in this paper
            seen = {_normalized(s) for s in split_sentences(clean_text(paper.get("abstract", "")))}
            for piece in pieces:
                piece["original_tokens"] = approx_tokens(piece["text"])
                sentences = []
                for sentence in split_sentences(clean_text(piece["text"])):
                    key = _normalized(sentence)
                    if key and key not in seen:
                        seen.add(key)
                        sentences.append(sentence)
                piece["sentences"] = sentences
            all_pieces.extend(pieces)

        # Step 3: one embedding call for every sentence of the question's papers
        flat = [s for piece in all_pieces for s in piece["sentences"]]
        scores = self._scores(query, flat)
        start = 0
        trimmed = 0
        for piece in all_pieces:
            sentences = piece["sentences"]
            piece_scores = scores[start:start + len(sentences)]
            start += len(sentences)

            whole = " ".join(sentences)
            if approx_tokens(whole) <= settings.min_tokens_to_trim:
                piece["text"] = whole
                continue
            kept = select_sentences(sentences, piece_scores, settings)
            kept_text = " ".join(sentences[i] for i in kept)
            if len(kept_text) > settings.keep_whole_above * len(whole):
                piece["text"] = whole
            else:
                piece["text"] = join_kept(sentences, kept)
                trimmed += 1

        # Step 4: titles and abstracts always go in; the rest by tier, then rank
        fixed = sum(approx_tokens(f"{p.get('title', '')} {p.get('abstract', '')}") + 25 for p in papers)
        main_is_results = {p["rank"] for p in all_pieces if p["kind"] == "main" and _is_results(p)}

        def tier(piece):
            if piece["kind"] == "main":
                return 1
            if piece["kind"] == "limitations":
                return 2
            return 4 if piece["rank"] in main_is_results else 3

        used = fixed
        dropped = []
        for piece in sorted(all_pieces, key=lambda p: (tier(p), p["rank"])):
            cost = approx_tokens(piece["text"]) + 20  # + its label line
            if not piece["text"] or used + cost > settings.budget_tokens:
                piece["keep"] = False
                if piece["text"]:
                    dropped.append({"paper_id": papers[piece["rank"]]["paper_id"],
                                    "kind": piece["kind"], "chunk_id": piece["chunk_id"]})
                continue
            piece["keep"] = True
            used += cost

        for rank, paper in enumerate(papers):
            pieces = [p for p in all_pieces if p["rank"] == rank]
            main = pieces[0]
            paper["best_chunk_text"] = main["text"] if main["keep"] else ""
            paper["passages"] = [
                {**p["passage"], "text": p["text"]} for p in pieces[1:] if p["keep"]
            ]

        before = sum(approx_tokens(f"{p.get('title', '')} {p.get('abstract', '')}") + 25 for p in papers) + sum(
            p["original_tokens"] + 20 for p in all_pieces)
        stats = {
            "tokens_before": before,
            "tokens_after": used,
            "budget": settings.budget_tokens,
            "trimmed_passages": trimmed,
            "dropped": dropped,
        }
        return papers, stats


def _is_results(piece):
    if piece["section_type"]:
        return piece["section_type"] in RESULT_TYPES
    return bool(re.search(r"result|experiment|evaluation", piece["section"], re.IGNORECASE))
