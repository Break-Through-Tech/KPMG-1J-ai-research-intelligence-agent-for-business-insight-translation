SYSTEM_PERSONA = """You are a Senior AI & Financial Research Analyst at KPMG.
Your role is to translate complex AI research paper findings into actionable executive briefs for business stakeholders.
"""

RAG_PROMPT_TEMPLATE = """
{system_persona}

Instructions:
1. Answer the user question based ONLY on the provided research context below.
2. Maintain a professional, executive tone suitable for C-suite decision-makers.
3. Use inline citation brackets for every claim made (e.g., [Title: <title>, Section: <section>]).
4. If the provided context does not contain sufficient information to answer the query, clearly state what information is missing.

Retrieved Context:
{context_str}

User Question:
{user_query}

Executive Summary:
"""


def format_rag_prompt(user_query: str, retrieved_docs: list, retrieved_metas: list) -> str:
    context_blocks = []
    for idx, (doc, meta) in enumerate(zip(retrieved_docs, retrieved_metas), 1):
        title = meta.get("title", "Unknown Title")
        section = meta.get("section", "General")
        context_blocks.append(
            f"--- Source [{idx}] ---\nPaper Title: {title}\nSection: {section}\nContent: {doc}\n"
        )
    
    full_context = "\n".join(context_blocks)
    return RAG_PROMPT_TEMPLATE.format(
        system_persona=SYSTEM_PERSONA,
        context_str=full_context,
        user_query=user_query
    )


if __name__ == "__main__":
    print("--- Testing Prompt Formatting ---")
    dummy_query = "What are the financial risks of adopting enterprise LLMs?"
    dummy_docs = [
        "LLM deployment carries upfront infrastructure costs and ongoing API token fees that can fluctuate unpredictably."
    ]
    dummy_metas = [
        {"title": "Enterprise AI Risk Assessment", "section": "Financial Projections"}
    ]

    formatted_prompt = format_rag_prompt(dummy_query, dummy_docs, dummy_metas)
    print(formatted_prompt)
