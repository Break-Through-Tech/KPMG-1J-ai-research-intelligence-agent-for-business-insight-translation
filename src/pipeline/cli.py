# Command line entry point for the end-to-end pipeline
#
# Ask one question:
# python -m src.pipeline.cli "Can an AI model's step-by-step reasoning be trusted?"
#
# Run every benchmark query and save the answers:
# python -m src.pipeline.cli --benchmark evaluation/benchmark_queries.csv
#
# Retrievers (--retriever), both search the LanceDB index from src/indexing:
#   lance-combined  title/abstract search + chunk search merged with RRF (default)
#   lance           hybrid chunk search only, grouped into papers
#
# Each answer also gets a business brief (src/translation) unless
# --no-translate is given; --audience picks executive, risk or technical.

import argparse

from .llm import DEFAULT_PROVIDER, LLM, PROVIDERS
from .pipeline import answer_query, run_benchmark
from src.translation.prompts import AUDIENCES, DEFAULT_AUDIENCE


def print_answer(result):

    print("\n" + result["summary"])

    print("\nSources:")
    for number, source in enumerate(result["sources"], start=1):
        print(f"  [{number}] {source['paper_id']}  {source['title']}")
        print(f"      {source['arxiv_url']}")

    if result["truncated"]:
        print("\nWARNING: summary was cut off (hit the token limit), "
              "try a higher --max-tokens")

    check = result["citation_check"]
    if check["cited_not_retrieved"]:
        print("\nWARNING: summary cites papers that were not retrieved: "
              + ", ".join(check["cited_not_retrieved"]))

    insight = result.get("business_insight")
    if not insight:
        return

    print(f"\n========== Business brief ({insight['audience']}) ==========\n")
    print(insight["brief"])

    if insight["truncated"]:
        print("\nWARNING: business brief was cut off (hit the token limit), "
              "try a higher --max-tokens")

    brief_check = insight["citation_check"]
    if brief_check["cited_not_in_summary"]:
        print("\nWARNING: business brief cites papers the summary didn't: "
              + ", ".join(brief_check["cited_not_in_summary"]))


def main():

    parser = argparse.ArgumentParser(
        description="Answer research questions with retrieval + summarization"
    )

    parser.add_argument(
        "query",
        nargs="?",
        help="question to answer (leave out when using --benchmark)"
    )

    parser.add_argument(
        "--benchmark",
        help="CSV with query_id, category, query, expected_paper_ids"
    )

    parser.add_argument(
        "--output",
        default="evaluation/results/end_to_end_outputs.jsonl"
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=5
    )

    parser.add_argument(
        "--papers",
        default="data/papers_clean.parquet"
    )

    parser.add_argument(
        "--retriever",
        choices=["lance-combined", "lance"],
        default="lance-combined"
    )

    parser.add_argument(
        "--index-dir",
        default="data/index"
    )

    parser.add_argument(
        "--provider",
        choices=list(PROVIDERS),
        default=DEFAULT_PROVIDER,
        help="LLM service: groq (GROQ_API_KEY, default), "
             "nvidia (NVIDIA_API_KEY, free key at build.nvidia.com) or gemini (GEMINI_API_KEY)"
    )

    parser.add_argument(
        "--model",
        help=", ".join(f"{name}: {settings['model']}" for name, settings in PROVIDERS.items())
             + " by default"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=5,
        help="times to wait and retry a rate limited request"
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help="seconds to pause between benchmark questions"
    )

    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high", "none"],
        default="low",
        help="none leaves the setting out, for models that don't accept it"
    )

    parser.add_argument(
        "--no-translate",
        action="store_true",
        help="skip the business brief (saves one LLM call per question)"
    )

    parser.add_argument(
        "--audience",
        choices=list(AUDIENCES),
        default=DEFAULT_AUDIENCE,
        help="who the business brief is written for"
    )

    args = parser.parse_args()

    if not args.query and not args.benchmark:
        parser.error("give a question or --benchmark")

    # Check the API key before the slow retriever startup
    llm = LLM(
        provider=args.provider,
        model=args.model,
        max_tokens=args.max_tokens,
        reasoning_effort=None if args.reasoning_effort == "none" else args.reasoning_effort,
        max_retries=args.max_retries
    )

    # Imported here because it needs lancedb and loads the embedding model
    from src.rag.lance_retriever import LanceCombinedRetriever, LanceRetriever

    retriever_class = (
        LanceCombinedRetriever if args.retriever == "lance-combined"
        else LanceRetriever
    )

    retriever = retriever_class(
        papers_path=args.papers,
        index_dir=args.index_dir
    )

    if args.benchmark:
        run_benchmark(
            args.benchmark,
            args.output,
            retriever,
            llm,
            top_k=args.top_k,
            delay=args.delay,
            translate=not args.no_translate,
            audience=args.audience
        )
    else:
        print_answer(answer_query(
            args.query,
            retriever,
            llm,
            top_k=args.top_k,
            translate=not args.no_translate,
            audience=args.audience
        ))


if __name__ == "__main__":
    main()
