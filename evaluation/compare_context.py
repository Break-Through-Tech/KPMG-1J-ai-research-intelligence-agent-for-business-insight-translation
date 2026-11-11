# Compares the paper text sent to the summarization LLM with and without the
# compressor (src/pipeline/compress.py), on the benchmark questions.
#
# Offline (no API key, no LLM calls):
#   python -m evaluation.compare_context
# reports estimated tokens and what survives compression: every number, every
# caveat sentence ("however", "only", "fails"...), and the abstracts.
#
# With the LLM (2-3 calls per question; reads the key from .env):
#   python -m evaluation.compare_context --llm --provider nvidia --questions Q10,Q11,Q12,Q13,Q14,Q15
# writes a summary per question for each variant:
#   full       the current pipeline (no compression, full instructions)
#   compressed compressed paper text, full instructions
#   compact    compressed paper text, shorter instructions (one example)
# and checks each one: provider-counted prompt tokens, citations, numbers in the
# summary that aren't in the papers, and whether limitations were found.

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd

from src.pipeline.compress import CAVEAT, CompressSettings, ContextCompressor, approx_tokens, clean_text, split_sentences
from src.pipeline.pipeline import check_citations, format_retrieved_content
from src.summarization.prompts import (
    SUMMARIZATION_SYSTEM_PROMPT,
    SUMMARIZATION_SYSTEM_PROMPT_COMPACT,
    build_summarization_prompt,
)

NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*%?")
NO_LIMITATIONS = "does not specify limitations"

VARIANTS = {
    "full": {"compress": False, "compact": False},
    "compressed": {"compress": True, "compact": False},
    "compact": {"compress": True, "compact": True},
}


ARXIV_ID = re.compile(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b")


def numbers(text):
    """Numbers as written, leaving out arXiv IDs and single digits like list markers."""
    text = ARXIV_ID.sub(" ", text)
    return {n.rstrip(".,") for n in NUMBER.findall(text) if len(n.rstrip("%")) > 1 or "%" in n}


def paper_texts(paper):
    """The non-abstract texts of one paper, cleaned the way the compressor cleans them."""
    texts = [paper.get("best_chunk_text") or ""]
    texts += [p.get("text") or "" for p in paper.get("passages") or []]
    return [clean_text(t) for t in texts if t]


def retention(papers, compressed):
    """
    Share of the numbers and caveat sentences in the full passages that are still
    in the compressed text: overall, and only in passages the budget kept
    (which isolates the sentence selection from the budget).
    """
    out = {"numbers": [0, 0], "numbers_kept_passages": [0, 0], "caveats": [0, 0], "caveats_kept_passages": [0, 0]}

    for paper, short in zip(papers, compressed):
        sent = " ".join(paper_texts(short))
        kept_ids = {short.get("chunk_id")} if short.get("best_chunk_text") else set()
        kept_ids |= {p.get("chunk_id") for p in short.get("passages") or []}

        pieces = [(paper.get("chunk_id"), paper.get("best_chunk_text") or "")]
        pieces += [(p.get("chunk_id"), p.get("text") or "") for p in paper.get("passages") or []]

        for chunk_id, text in pieces:
            text = clean_text(text)
            kept = chunk_id in kept_ids
            for n in numbers(text):
                found = n in sent
                out["numbers"][0] += found
                out["numbers"][1] += 1
                if kept:
                    out["numbers_kept_passages"][0] += found
                    out["numbers_kept_passages"][1] += 1
            for sentence in split_sentences(text):
                if CAVEAT.search(sentence):
                    found = sentence in sent
                    out["caveats"][0] += found
                    out["caveats"][1] += 1
                    if kept:
                        out["caveats_kept_passages"][0] += found
                        out["caveats_kept_passages"][1] += 1
    return out


def load_questions(path, wanted):
    queries = pd.read_csv(path)
    if wanted:
        ids = [q.strip() for q in wanted.split(",")]
        queries = queries[queries["query_id"].isin(ids)]
    return queries


def offline(queries, retriever, compressor, top_k):
    rows = []
    totals = {}
    for _, row in queries.iterrows():
        papers = retriever.search(row["query"], top_k=top_k)
        short, stats = compressor.compress(row["query"], papers)
        full_text = format_retrieved_content(papers)
        short_text = format_retrieved_content(short, excerpts=True)
        r = retention(papers, short)
        for key, (hit, total) in r.items():
            totals.setdefault(key, [0, 0])
            totals[key][0] += hit
            totals[key][1] += total
        rows.append({
            "query_id": row["query_id"],
            "full_tokens": approx_tokens(full_text),
            "compressed_tokens": approx_tokens(short_text),
            "saved": 1 - approx_tokens(short_text) / approx_tokens(full_text),
            "dropped": ", ".join(f"{d['kind']}#{[p['paper_id'] for p in papers].index(d['paper_id']) + 1}"
                                 for d in stats["dropped"]),
            **{k: f"{h}/{t}" for k, (h, t) in r.items()},
        })
        print(f"{row['query_id']}: {rows[-1]['full_tokens']:,} -> {rows[-1]['compressed_tokens']:,} tokens")
    return pd.DataFrame(rows), totals


def run_llm(queries, retriever, compressor, llm, top_k, variants, output, delay):
    output.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if output.exists():
        for line in output.read_text().splitlines():
            if line.strip():
                record = json.loads(line)
                done.add((record["query_id"], record["variant"]))

    with output.open("a", encoding="utf-8") as handle:
        for _, row in queries.iterrows():
            papers = retriever.search(row["query"], top_k=top_k)
            short, stats = compressor.compress(row["query"], papers)
            full_numbers = numbers(" ".join(
                clean_text(p.get("abstract", "")) + " " + " ".join(paper_texts(p)) for p in papers))

            for name in variants:
                if (row["query_id"], name) in done:
                    continue
                setting = VARIANTS[name]
                use = short if setting["compress"] else papers
                content = format_retrieved_content(use, excerpts=setting["compress"])
                prompt = build_summarization_prompt(row["query"], content, compact=setting["compact"])
                system = SUMMARIZATION_SYSTEM_PROMPT_COMPACT if setting["compact"] else SUMMARIZATION_SYSTEM_PROMPT

                print(f"{row['query_id']} {name}...", flush=True)
                started = time.monotonic()
                summary = llm.generate(system, prompt)
                seconds = time.monotonic() - started

                summary_numbers = numbers(summary)
                record = {
                    "query_id": row["query_id"],
                    "query": row["query"],
                    "variant": name,
                    "prompt_tokens": (llm.last_usage or {}).get("prompt_tokens"),
                    "completion_tokens": (llm.last_usage or {}).get("completion_tokens"),
                    "estimated_prompt_tokens": approx_tokens(system + prompt),
                    "seconds": round(seconds, 1),
                    "truncated": llm.last_finish_reason == "length",
                    "citations": check_citations(summary, papers),
                    # numbers the summary states that appear nowhere in the retrieved papers
                    "numbers_not_in_papers": sorted(summary_numbers - full_numbers),
                    "numbers_in_summary": len(summary_numbers),
                    "limitations_found": NO_LIMITATIONS not in summary.lower(),
                    "context": stats if setting["compress"] else None,
                    "summary": summary,
                }
                handle.write(json.dumps(record) + "\n")
                handle.flush()
                if delay:
                    time.sleep(delay)

    records = [json.loads(line) for line in output.read_text().splitlines() if line.strip()]
    for r in records:
        r["numbers_not_in_papers"] = [n for n in r["numbers_not_in_papers"] if not ARXIV_ID.fullmatch(n)]
    table = pd.DataFrame([{
        "query_id": r["query_id"], "variant": r["variant"], "prompt_tokens": r["prompt_tokens"],
        "completion_tokens": r["completion_tokens"], "seconds": r["seconds"],
        "cited": len(r["citations"]["cited"]), "bad_citations": len(r["citations"]["cited_not_retrieved"]),
        "numbers": r["numbers_in_summary"], "numbers_not_in_papers": len(r["numbers_not_in_papers"]),
        "limitations_found": r["limitations_found"], "truncated": r["truncated"],
    } for r in records])
    return table


def main():
    parser = argparse.ArgumentParser(description="Compare summary context with and without compression")
    parser.add_argument("--benchmark", default="evaluation/benchmark_queries.csv")
    parser.add_argument("--questions", help="comma-separated query ids, e.g. Q10,Q11 (default: all)")
    parser.add_argument("--papers", default="data/papers_clean.parquet")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--budget", type=int, default=CompressSettings.budget_tokens)
    parser.add_argument("--neighbors", type=int, default=CompressSettings.neighbors)
    parser.add_argument("--llm", action="store_true", help="also write summaries with each variant")
    parser.add_argument("--variants", default="full,compressed,compact")
    parser.add_argument("--provider", default="nvidia")
    parser.add_argument("--model")
    parser.add_argument("--delay", type=float, default=0)
    parser.add_argument("--output", default="evaluation/results/context_compression")
    args = parser.parse_args()

    from src.rag.lance_retriever import LanceCombinedRetriever

    retriever = LanceCombinedRetriever(papers_path=args.papers, index_dir=args.index_dir)
    compressor = ContextCompressor(
        retriever.embedder, CompressSettings(budget_tokens=args.budget, neighbors=args.neighbors))
    queries = load_questions(args.benchmark, args.questions)
    output = Path(args.output)

    if args.llm:
        from src.pipeline.llm import LLM

        llm = LLM(provider=args.provider, model=args.model)
        table = run_llm(queries, retriever, compressor, llm, args.top_k,
                        args.variants.split(","), output.with_name(output.name + "_llm.jsonl"), args.delay)
        print(table.to_string(index=False))
        print(table.groupby("variant")[["prompt_tokens", "completion_tokens", "seconds",
                                        "bad_citations", "numbers_not_in_papers"]].mean().round(1))
        table.to_csv(output.with_name(output.name + "_llm.csv"), index=False)
        return

    table, totals = offline(queries, retriever, compressor, args.top_k)
    print(table.to_string(index=False))
    print(f"\nmean tokens: {table['full_tokens'].mean():,.0f} -> {table['compressed_tokens'].mean():,.0f} "
          f"({table['saved'].mean():.0%} saved)")
    for key, (hit, total) in totals.items():
        print(f"{key}: {hit}/{total} = {hit / max(total, 1):.1%}")
    table.to_csv(output.with_name(output.name + "_offline.csv"), index=False)


if __name__ == "__main__":
    main()
