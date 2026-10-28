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


def test_answer_query_flags_truncated_summary():
    llm = FakeLLM()
    llm.last_finish_reason = "length"

    result = answer_query("Long question?", FakeRetriever(make_papers()), llm)
    assert result["truncated"] is True

    llm.last_finish_reason = "stop"

    result = answer_query("Long question?", FakeRetriever(make_papers()), llm)
    assert result["truncated"] is False


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
    # (two LLM calls per query: summary + business brief)
    assert run_benchmark(benchmark, output, FakeRetriever(make_papers()), llm) == 0
    assert len(llm.calls) == 4
    assert rows[0]["business_insight"]["brief"] == llm.response


def test_run_benchmark_without_translation_makes_one_call_per_query(tmp_path):
    benchmark = tmp_path / "queries.csv"
    pd.DataFrame([
        {"query_id": "Q01", "category": "general", "query": "First?", "expected_paper_ids": None}
    ]).to_csv(benchmark, index=False)

    output = tmp_path / "out.jsonl"
    llm = FakeLLM()

    run_benchmark(benchmark, output, FakeRetriever(make_papers()), llm, translate=False)

    assert len(llm.calls) == 1
    assert json.loads(output.read_text())["business_insight"] is None


# ---------- business translation ----------

from src.translation.prompts import (
    AUDIENCES,
    BUSINESS_SECTIONS,
    BUSINESS_SYSTEM_PROMPT,
    FEW_SHOT_EXAMPLES,
    build_business_prompt
)


class ScriptedLLM:
    """Returns the given responses in order: summary first, then brief."""

    def __init__(self, responses, finish_reasons=None):
        self.responses = list(responses)
        self.finish_reasons = list(finish_reasons or [])
        self.calls = []
        self.last_finish_reason = None

    def generate(self, system_prompt, user_prompt):
        self.calls.append((system_prompt, user_prompt))
        if self.finish_reasons:
            self.last_finish_reason = self.finish_reasons.pop(0)
        return self.responses.pop(0)


SUMMARY = "Key Findings: 31.6% of correct answers had invalid traces. [2609.38107v1]"


def test_brief_is_written_from_the_summary_only():
    llm = ScriptedLLM([SUMMARY, "## Bottom Line\nNot on its own. [2609.38107v1]"])

    result = answer_query("Can we trust AI explanations?", FakeRetriever(make_papers()), llm,
                          audience="risk")

    system_prompt, user_prompt = llm.calls[1]
    assert system_prompt == BUSINESS_SYSTEM_PROMPT
    assert SUMMARY in user_prompt
    assert AUDIENCES["risk"] in user_prompt
    # the raw paper text is not sent to step 2
    assert "Plan+ReAct preserved plans in 22-45% of runs." not in user_prompt

    insight = result["business_insight"]
    assert insight["audience"] == "risk"
    assert insight["brief"].startswith("## Bottom Line")
    assert insight["citation_check"]["cited_not_in_summary"] == []


def test_brief_citation_not_in_summary_is_flagged():
    # 2609.38108 was retrieved but the summary never cited it,
    # and 2609.99999 was never retrieved at all
    llm = ScriptedLLM([SUMMARY, "Point [2609.38108v1]. Another [2609.99999v1]."])

    check = answer_query("Q?", FakeRetriever(make_papers()), llm)["business_insight"]["citation_check"]

    assert check["cited_not_in_summary"] == ["2609.38108", "2609.99999"]
    assert check["cited_not_retrieved"] == ["2609.99999"]


def test_summary_truncation_is_kept_when_brief_finishes():
    llm = ScriptedLLM([SUMMARY, "brief"], finish_reasons=["length", "stop"])

    result = answer_query("Q?", FakeRetriever(make_papers()), llm)

    assert result["truncated"] is True
    assert result["business_insight"]["truncated"] is False


def test_translate_false_makes_one_call():
    llm = FakeLLM()

    result = answer_query("Q?", FakeRetriever(make_papers()), llm, translate=False)

    assert len(llm.calls) == 1
    assert result["business_insight"] is None


def test_build_business_prompt_rejects_bad_input():
    with pytest.raises(ValueError):
        build_business_prompt("Q?", "summary", audience="intern")
    with pytest.raises(ValueError):
        build_business_prompt("Q?", "   ")
    with pytest.raises(ValueError):
        build_business_prompt("", "summary")


def test_few_shot_briefs_use_all_sections_and_only_summary_numbers():
    import re

    for example in FEW_SHOT_EXAMPLES:
        headings = re.findall(r"^## (.+)$", example["brief"], re.MULTILINE)
        assert headings == BUSINESS_SECTIONS

        body, sources = example["brief"].split("## Sources")

        # the examples must model the rule: no numbers that aren't in the summary
        for number in re.findall(r"\d+(?:\.\d+)?%?", body):
            assert number in example["summary"], number

        # Sources lists exactly the papers cited in the brief
        cited = set(re.findall(r"\[(\d{4}\.\d{4,5}v\d+)\]", body))
        listed = {item.strip() for item in sources.split(",") if item.strip()}
        assert listed == cited

        # the examples model the length rule
        assert len(example["brief"].split()) < 200

        # a summary without limitations doesn't mean the research has none
        assert "did not report limitations" not in example["brief"]


# ---------- rate limits ----------

import httpx
import openai
import pytest

from src.pipeline.llm import LLM, retry_wait_seconds

GROQ_PER_MINUTE = (
    "Rate limit reached for model `openai/gpt-oss-120b` on tokens per minute (TPM): "
    "Limit 8000, Used 6000, Requested 5000. Please try again in 1m2.5s."
)
GROQ_PER_DAY = (
    "Rate limit reached for model `openai/gpt-oss-120b` on tokens per day (TPD): "
    "Limit 200000, Used 198628, Requested 4998. Please try again in 9m48s."
)
GEMINI_PER_MINUTE = (
    "Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, "
    "quotaId: GenerateRequestsPerMinutePerProjectPerModel-FreeTier, 'retryDelay': '34s'"
)


def rate_limit_error(message, headers=None):
    request = httpx.Request("POST", "https://example.com/chat/completions")
    response = httpx.Response(429, request=request, headers=headers or {})
    return openai.RateLimitError(message, response=response, body=None)


class FlakyCompletions:
    """Raises the given errors in order, then returns a normal response."""

    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        message = type("Message", (), {"content": "Summary [2609.38107v1]"})
        choice = type("Choice", (), {"message": message, "finish_reason": "stop"})
        return type("Response", (), {"choices": [choice]})


def make_llm(monkeypatch, errors, max_retries=5):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    waits = []
    llm = LLM(provider="groq", max_retries=max_retries, sleep=waits.append)
    completions = FlakyCompletions(errors)
    llm.client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})})
    return llm, completions, waits


def test_wait_time_comes_from_header_then_message_then_backoff():
    assert retry_wait_seconds(rate_limit_error("slow down", {"retry-after": "7"}), 0) == 7
    assert retry_wait_seconds(rate_limit_error(GROQ_PER_MINUTE), 0) == 62.5
    assert retry_wait_seconds(rate_limit_error(GEMINI_PER_MINUTE), 0) == 34
    assert retry_wait_seconds(rate_limit_error("slow down"), 2) == 60


def test_per_minute_limit_waits_and_retries(monkeypatch):
    llm, completions, waits = make_llm(monkeypatch, [rate_limit_error(GEMINI_PER_MINUTE)])

    assert llm.generate("system", "user") == "Summary [2609.38107v1]"
    assert completions.calls == 2
    assert waits == [35]


def test_daily_limit_stops_without_waiting(monkeypatch):
    llm, completions, waits = make_llm(monkeypatch, [rate_limit_error(GROQ_PER_DAY)])

    with pytest.raises(RuntimeError, match="daily groq limit"):
        llm.generate("system", "user")

    assert completions.calls == 1
    assert waits == []


def test_gives_up_after_max_retries(monkeypatch):
    errors = [rate_limit_error("slow down") for _ in range(3)]
    llm, completions, waits = make_llm(monkeypatch, errors, max_retries=2)

    with pytest.raises(openai.RateLimitError):
        llm.generate("system", "user")

    assert completions.calls == 3
    assert len(waits) == 2


def test_run_benchmark_pauses_between_queries_only(tmp_path):
    benchmark = tmp_path / "queries.csv"
    pd.DataFrame([
        {"query_id": f"Q0{i}", "category": "general", "query": f"Question {i}?", "expected_paper_ids": None}
        for i in range(1, 4)
    ]).to_csv(benchmark, index=False)

    pauses = []
    run_benchmark(benchmark, tmp_path / "out.jsonl", FakeRetriever(make_papers()), FakeLLM(),
                  delay=10, sleep=pauses.append)

    assert pauses == [10, 10]


GEMINI_REAL_ERROR = (
    "Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current quota, please check "
    "your plan and billing details. \\n* Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 5, model: gemini-3.8-flash"
    "\\nPlease retry in 13.364181756s.', 'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', 'quotaValue': '5'}]}, "
    "{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '13s'}]}}]"
)


def test_real_gemini_per_minute_error_is_retried(monkeypatch):
    llm, completions, waits = make_llm(monkeypatch, [rate_limit_error(GEMINI_REAL_ERROR)])

    assert llm.generate("system", "user") == "Summary [2609.38107v1]"
    assert waits == [pytest.approx(14.364181756)]


class RecordingCompletions(FlakyCompletions):
    """Keeps the arguments of every request."""

    def __init__(self):
        super().__init__([])
        self.kwargs = []

    def create(self, **kwargs):
        self.kwargs.append(kwargs)
        return super().create(**kwargs)


@pytest.mark.parametrize("effort, sent", [("low", {"reasoning_effort": "low"}), (None, {})])
def test_reasoning_effort_is_left_out_when_none(monkeypatch, effort, sent):
    # some models (e.g. on NVIDIA) reject the setting, so None must not send it at all
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    llm = LLM(provider="nvidia", reasoning_effort=effort)
    completions = RecordingCompletions()
    llm.client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})})

    llm.generate("system", "user")

    assert {k: v for k, v in completions.kwargs[0].items() if k == "reasoning_effort"} == sent
