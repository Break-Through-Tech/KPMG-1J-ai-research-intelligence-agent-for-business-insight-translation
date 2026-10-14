import json

import pandas as pd

from src.pipeline.pipeline import (
    NO_RESULTS_MESSAGE,
    answer_query,
    check_citations,
    format_retrieved_content,
    run_benchmark
)
from src.summarization.prompts import SUMMARIZATION_SYSTEM_PROMPT


def make_papers():
    """
    Two results in the format CombinedRetriever.search returns.
    """

    return [
        {
            "paper_id": "2609.38107v1",
            "title": "Correct Answers, Invalid Traces",
            "abstract": "Correct answers can come with invalid reasoning traces.",
            "score": 0.032,
            "chunk_id": "2609.38107v1::0003",
            "chunk_paper_id": "2609.38107v1",
            "best_chunk_section": "4 Results",
            "best_chunk_text": "31.6% of correct answers had invalid traces.",
            "chunk_distance": 0.21
        },
        {
            "paper_id": "2609.38108v1",
            "title": "Do LLM Agents Execute the Plans They Declare?",
            "abstract": "Agents often do not follow their declared plans.",
            "score": 0.030,
            "chunk_id": "2609.38108v1::0001",
            "chunk_paper_id": "2609.38108v1",
            "best_chunk_section": "1 Introduction",
            "best_chunk_text": "Plan+ReAct preserved plans in 22-45% of runs.",
            "chunk_distance": 0.25
        }
    ]


class FakeRetriever:

    def __init__(self, papers):
        self.papers = papers
        self.calls = []

    def search(self, query, top_k=5):
        self.calls.append((query, top_k))
        return self.papers[:top_k]


class FakeLLM:

    def __init__(self, response="Key Findings: traces fail. [2609.38107v1]"):
        self.response = response
        self.calls = []

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_format_retrieved_content_includes_ids_and_evidence():
    content = format_retrieved_content(make_papers())

    assert "[2609.38107v1] Title: Correct Answers, Invalid Traces" in content
    assert "Correct answers can come with invalid reasoning traces." in content
    assert "Chunk ID: 2609.38108v1::0001" in content
    assert "31.6% of correct answers had invalid traces." in content


def test_answer_query_sends_retrieved_content_to_llm():
    retriever = FakeRetriever(make_papers())
    llm = FakeLLM()

    result = answer_query("Can reasoning traces be trusted?", retriever, llm, top_k=2)

    assert retriever.calls == [("Can reasoning traces be trusted?", 2)]

    system_prompt, user_prompt = llm.calls[0]
    assert system_prompt == SUMMARIZATION_SYSTEM_PROMPT
    assert "Can reasoning traces be trusted?" in user_prompt
    assert "Plan+ReAct preserved plans in 22-45% of runs." in user_prompt

    assert result["summary"] == llm.response
    assert [s["paper_id"] for s in result["sources"]] == ["2609.38107v1", "2609.38108v1"]
    assert result["sources"][0]["arxiv_url"] == "https://arxiv.org/abs/2609.38107"


def test_check_citations_flags_made_up_and_uncited_papers():
    summary = "Finding one [2609.38107v1]. Finding two [2609.99999v1]."

    check = check_citations(summary, make_papers())

    assert check["cited"] == ["2609.38107", "2609.99999"]
    assert check["cited_not_retrieved"] == ["2609.99999"]
    assert check["retrieved_not_cited"] == ["2609.38108"]


def test_check_citations_ignores_version_differences():
    check = check_citations("Supported claim [2609.38107v2].", make_papers()[:1])

    assert check["cited_not_retrieved"] == []


def test_no_results_skips_llm():
    llm = FakeLLM()

    result = answer_query("Something not in the corpus?", FakeRetriever([]), llm)

    assert llm.calls == []
    assert result["summary"] == NO_RESULTS_MESSAGE
    assert result["sources"] == []


def test_run_benchmark_writes_one_line_per_query_and_resumes(tmp_path):
    benchmark = tmp_path / "queries.csv"
    pd.DataFrame([
        {"query_id": "Q01", "category": "general", "query": "First?", "expected_paper_ids": None},
        {"query_id": "Q02", "category": "specific", "query": "Second?", "expected_paper_ids": "2609.38107v1"}
    ]).to_csv(benchmark, index=False)

    output = tmp_path / "out.jsonl"
    llm = FakeLLM()

    assert run_benchmark(benchmark, output, FakeRetriever(make_papers()), llm) == 2

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["query_id"] for row in rows] == ["Q01", "Q02"]
    assert rows[0]["expected_paper_ids"] == ""
    assert rows[1]["expected_paper_ids"] == "2609.38107v1"

    # Running again skips queries that are already answered
    assert run_benchmark(benchmark, output, FakeRetriever(make_papers()), llm) == 0
    assert len(llm.calls) == 2
