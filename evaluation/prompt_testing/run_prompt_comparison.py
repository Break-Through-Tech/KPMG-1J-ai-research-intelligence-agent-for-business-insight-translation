"""Test business prompt v2 against saved baseline summaries."""

import hashlib
import json
from pathlib import Path

from src.pipeline.llm import LLM
from src.pipeline.pipeline import check_citations
from evaluation.prompt_testing.business_prompt_v2 import (
    BUSINESS_SYSTEM_PROMPT_V2,
    build_business_prompt_v2,
)


QUESTION_IDS = ["Q12", "Q14", "Q15"]
BASELINE = Path("evaluation/end_to_end")
OUTPUT = Path(
    "evaluation/prompt_testing/results/prompt_v2"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    outputs_folder = OUTPUT / "outputs"
    outputs_folder.mkdir(parents=True, exist_ok=True)
    inputs = {}

    # Prepare all inputs before making any API requests.
    for query_id in QUESTION_IDS:
        folder = BASELINE / f"{query_id.lower()}_test"
        summary = load_json(folder / "output.json")
        baseline_brief = load_json(folder / "business_insight.json")
        sources = load_json(folder / "sources.json")

        if summary.get("truncated"):
            raise ValueError(f"{query_id}: baseline summary is truncated.")

        user_prompt = build_business_prompt_v2(
            summary["query"],
            summary["summary"],
            audience="executive",
        )

        inputs[query_id] = {
            "query": summary["query"],
            "summary": summary["summary"],
            "baseline_brief": baseline_brief["brief"],
            "sources": sources,
            "user_prompt": user_prompt,
        }

    settings = {
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "temperature": 0.1,
        "max_tokens": 4096,
        "reasoning_effort": "low",
        "audience": "executive",
        "question_ids": QUESTION_IDS,
        "system_prompt_sha256": text_hash(
            BUSINESS_SYSTEM_PROMPT_V2
        ),
        "input_sha256": {
            query_id: text_hash(
                json.dumps(data, sort_keys=True, ensure_ascii=False)
            )
            for query_id, data in inputs.items()
        },
    }

    settings_file = OUTPUT / "settings.json"

    if settings_file.exists():
        if load_json(settings_file) != settings:
            raise ValueError(
                "Prompt, inputs, or settings changed. "
                "Use a new output folder for a new experiment."
            )
    else:
        save_json(settings_file, settings)

    (OUTPUT / "system_prompt.txt").write_text(
        BUSINESS_SYSTEM_PROMPT_V2,
        encoding="utf-8",
    )

    llm = LLM(
        provider=settings["provider"],
        model=settings["model"],
        temperature=settings["temperature"],
        max_tokens=settings["max_tokens"],
        reasoning_effort=settings["reasoning_effort"],
    )

    # Same workaround used successfully in the baseline run.
    llm.client = llm.client.with_options(
        default_headers={"Accept-Encoding": "identity"}
    )

    for query_id, data in inputs.items():
        output_file = outputs_folder / f"{query_id.lower()}_business_v2.json"

        if output_file.exists():
            print(f"{query_id}: already saved; skipping.")
            continue

        # Save exactly what this test uses, before generation.
        save_json(
            outputs_folder / f"{query_id.lower()}_inputs.json",
            data,
        )

        print(f"\nGenerating revised brief for {query_id}...")

        brief = llm.generate(
            BUSINESS_SYSTEM_PROMPT_V2,
            data["user_prompt"],
        )

        citation_check = check_citations(brief, data["sources"])
        summary_citations = set(
            check_citations(
                data["summary"], data["sources"]
            )["cited"]
        )

        citation_check["cited_not_in_summary"] = [
            paper_id
            for paper_id in citation_check["cited"]
            if paper_id not in summary_citations
        ]

        result = {
            "query_id": query_id,
            "query": data["query"],
            "audience": "executive",
            "brief": brief,
            "truncated": llm.last_finish_reason == "length",
            "word_count": len(brief.split()),
            "citation_check": citation_check,
        }

        save_json(output_file, result)

        print("Saved:", output_file)
        print("Truncated:", result["truncated"])
        print("Approximate word count:", result["word_count"])
        print("Citation checks:", citation_check)

    print("\nPrompt test finished.")


if __name__ == "__main__":
    main()