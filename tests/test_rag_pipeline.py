import pytest
from src.prompts.templates import format_rag_prompt, SYSTEM_PERSONA


def test_format_rag_prompt_structure():
    """Verify that prompt formatting embeds context, persona, and question properly."""
    user_query = "What are the primary operational risks in AI deployment?"
    retrieved_docs = ["Operational risks include data drift, security vulnerabilities, and vendor lock-in."]
    retrieved_metas = [{"title": "AI Risk Governance Framework", "section": "Operational Security"}]

    prompt = format_rag_prompt(user_query, retrieved_docs, retrieved_metas)

    # Assertions to ensure essential components are present in output
    assert SYSTEM_PERSONA.strip() in prompt
    assert user_query in prompt
    assert "Paper Title: AI Risk Governance Framework" in prompt
    assert "Section: Operational Security" in prompt
    assert "Operational risks include data drift" in prompt


def test_format_rag_prompt_empty_context():
    """Verify behavior when no documents are returned by the retriever."""
    user_query = "Unknown query?"
    prompt = format_rag_prompt(user_query, [], [])

    assert user_query in prompt
    assert "Retrieved Context:" in prompt
