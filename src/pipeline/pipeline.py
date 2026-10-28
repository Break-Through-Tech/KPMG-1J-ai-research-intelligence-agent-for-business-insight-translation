# End-to-end pipeline:
# user query -> CombinedRetriever (top papers + evidence) -> summarization prompt -> LLM -> cited answer
#            -> business translation prompt (src/translation) -> LLM -> business brief

import json
import re
import time
from pathlib import Path

import pandas as pd

from src.summarization.prompts import (
    SUMMARIZATION_SYSTEM_PROMPT,
    build_summarization_prompt
)
from src.translation.prompts import (
    BUSINESS_SYSTEM_PROMPT,
    DEFAULT_AUDIENCE,
    build_business_prompt
)


# Matches citations like [2609.38107v1] or [2609.38107]
CITATION_PATTERN = re.compile(r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b")

NO_RESULTS_MESSAGE = (
    "No relevant research was found in the indexed papers for this question."
)


def base_id(paper_id):
    """
    Treat arXiv versions such as v1 and v2 as the same paper.
    """

    return re.sub(r"v\d+$", "", str(paper_id).strip())


def format_retrieved_content(papers):
    """
    Turn CombinedRetriever results into the text block the summarization
    prompt expects. Each paper is labelled with its ID so the LLM can cite it.
    """

    blocks = []

    for paper in papers:
        paper_id = paper["paper_id"]

        block = (
            f"[{paper_id}] Title: {paper.get('title', '')}\n"
            f"Abstract: {paper.get('abstract', '')}\n"
            f"Section: {paper.get('best_chunk_section', '')}\n"
            f"Chunk ID: {paper.get('chunk_id', '')}\n"
            f"{paper.get('best_chunk_text', '')}"
        )

        # results and limitations passages from the Lance retrievers, named by the
        # section they came from, so a conclusion standing in for a missing
        # limitations section isn't presented to the LLM as limitations
        for passage in paper.get("passages") or []:
            kind = passage.get("section_type") or passage["label"]
            block += (
                f"\n\n{kind.replace('_', ' ').capitalize()} passage "
                f"(Section: {passage['section']}, Chunk ID: {passage['chunk_id']}):\n"
                f"{passage['text']}"
            )

        blocks.append(block)

    return "\n\n".join(blocks)


def check_citations(summary, papers):
    """
    Compare the paper IDs cited in the summary with the papers retrieved.
    cited_not_retrieved should always be empty; anything there is a
    made-up citation.
    """

    retrieved = {base_id(paper["paper_id"]) for paper in papers}

    cited = []

    for match in CITATION_PATTERN.findall(summary):
        paper_id = base_id(match)

        if paper_id not in cited:
            cited.append(paper_id)

    return {
        "cited": cited,
        "cited_not_retrieved": [p for p in cited if p not in retrieved],
        "retrieved_not_cited": sorted(retrieved - set(cited))
    }


def _source_info(paper):
    """
    Keep the fields a reader needs to check a source.
    """

    return {
        "paper_id": paper["paper_id"],
        "title": paper.get("title", ""),
        "arxiv_url": f"https://arxiv.org/abs/{base_id(paper['paper_id'])}",
        "chunk_id": paper.get("chunk_id", ""),
        "section": paper.get("best_chunk_section", ""),
        "score": paper.get("score"),
        # the other passages the LLM read from this paper
        "passages": [
            {key: passage[key] for key in ("label", "section", "chunk_id")}
            for passage in paper.get("passages") or []
        ]
    }


def translate_summary(query, summary, papers, llm, audience=DEFAULT_AUDIENCE):
    """
    Step 2: turn the research summary into a business brief.
    The LLM only sees the summary, so the brief can't draw on anything
    step 1 didn't say. cited_not_in_summary should always be empty.
    """

    prompt = build_business_prompt(query, summary, audience)

    brief = llm.generate(BUSINESS_SYSTEM_PROMPT, prompt)

    check = check_citations(brief, papers)
    summary_cited = set(check_citations(summary, papers)["cited"])

    check["cited_not_in_summary"] = [
        paper_id for paper_id in check["cited"] if paper_id not in summary_cited
    ]

    return {
        "audience": audience,
        "brief": brief,
        "truncated": getattr(llm, "last_finish_reason", None) == "length",
        "citation_check": check
    }


def answer_query(query, retriever, llm, top_k=5, translate=True,
                 audience=DEFAULT_AUDIENCE):
    """
    Run one question through retrieval, summarization and (unless
    translate=False) business translation.

    retriever: anything with search(query, top_k) returning paper dicts
               (see src/rag/README_combined_retriever.md)
    llm:       anything with generate(system_prompt, user_prompt)
    """

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Query cannot be empty")

    papers = retriever.search(query, top_k=top_k)

    # Nothing to summarize, so don't ask the LLM to make something up
    if not papers:
        return {
            "query": query,
            "sources": [],
            "summary": NO_RESULTS_MESSAGE,
            "truncated": False,
            "citation_check": check_citations("", []),
            "business_insight": None
        }

    retrieved_content = format_retrieved_content(papers)
    prompt = build_summarization_prompt(query, retrieved_content)

    summary = llm.generate(SUMMARIZATION_SYSTEM_PROMPT, prompt)

    result = {
        "query": query,
        "sources": [_source_info(paper) for paper in papers],
        "summary": summary,
        # True when the LLM hit its token limit and the summary is cut off
        # (read before step 2, which overwrites last_finish_reason)
        "truncated": getattr(llm, "last_finish_reason", None) == "length",
        "citation_check": check_citations(summary, papers),
        "business_insight": None
    }

    if translate:
        result["business_insight"] = translate_summary(
            query, summary, papers, llm, audience
        )

    return result


def run_benchmark(benchmark_path, output_path, retriever, llm, top_k=5,
                  delay=0, sleep=time.sleep, translate=True,
                  audience=DEFAULT_AUDIENCE):
    """
    Answer every benchmark query and write one JSON line per query.
    Queries already in the output file are skipped, so a failed run
    (e.g. a rate limit) can be restarted without redoing finished work.
    delay: seconds to pause between queries, for low per-minute limits.
    translate: also write a business brief (a second LLM call per query).
    """

    queries = pd.read_csv(benchmark_path)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done = set()

    if output_path.exists():
        with output_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    done.add(json.loads(line)["query_id"])

    written = 0

    with output_path.open("a", encoding="utf-8") as handle:
        for _, row in queries.iterrows():
            if row["query_id"] in done:
                continue

            if written and delay:
                sleep(delay)

            print(f"Answering {row['query_id']}: {row['query']}")

            result = answer_query(row["query"], retriever, llm, top_k=top_k,
                                  translate=translate, audience=audience)

            record = {
                "query_id": row["query_id"],
                "category": row.get("category", ""),
                "expected_paper_ids": (
                    "" if pd.isna(row.get("expected_paper_ids"))
                    else row.get("expected_paper_ids", "")
                ),
                **result
            }

            handle.write(json.dumps(record) + "\n")
            handle.flush()
            written += 1

    print(f"Wrote {written} new answers to {output_path} "
          f"({len(done)} already done)")

    return written
