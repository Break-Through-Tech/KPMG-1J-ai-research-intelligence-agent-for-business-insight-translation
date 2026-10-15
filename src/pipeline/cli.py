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

import argparse

from .llm import DEFAULT_PROVIDER, LLM, PROVIDERS
from .pipeline import answer_query, run_benchmark


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
        help="LLM service: groq (GROQ_API_KEY) or gemini (GEMINI_API_KEY)"
    )

    parser.add_argument(
        "--model",
        help="defaults to openai/gpt-oss-120b on groq, gemini-2.5-flash on gemini"
    )

    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096
    )

    parser.add_argument(
        "--reasoning-effort",
        choices=["low", "medium", "high"],
        default="low"
    )

    args = parser.parse_args()

    if not args.query and not args.benchmark:
        parser.error("give a question or --benchmark")

    # Check the API key before the slow retriever startup
    llm = LLM(
        provider=args.provider,
        model=args.model,
        max_tokens=args.max_tokens,
        reasoning_effort=args.reasoning_effort
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
            top_k=args.top_k
        )
    else:
        print_answer(answer_query(args.query, retriever, llm, top_k=args.top_k))


if __name__ == "__main__":
    main()
