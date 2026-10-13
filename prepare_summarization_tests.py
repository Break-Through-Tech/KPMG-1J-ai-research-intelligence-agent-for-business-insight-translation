
# my idea: Prepare three real paper-based summarization tests
# without needing an LLM API key.

from pathlib import Path
import pandas as pd

from src.summarization.prompts import build_summarization_prompt

paper_ids = [
    "2609.38043v1",
    "2609.38070v1",
    "2609.38166v1"
]

questions = [
    "How much can the choice of simulated user change AI agent benchmarks?",
    "How can an AI model estimate uncertainty in its own answers?",
    "How can long-context language models reduce memory and compute costs?"
]

# Load the team's existing paper chunks.
df = pd.read_parquet("data/chunks.parquet")

output_folder = Path("reports/summarization")
output_folder.mkdir(parents=True, exist_ok=True)

for index in range(len(paper_ids)):
    paper_id = paper_ids[index]
    question = questions[index]

    paper_chunks = df[df["paper_id"] == paper_id]
    paper_chunks = paper_chunks.sort_values("chunk_index")

    if paper_chunks.empty:
        print("Paper not found:", paper_id)
        continue

    # Use a small, reproducible set of chunks for initial tests.
    selected_chunks = paper_chunks.head(8)

    source_parts = []

    for _, chunk in selected_chunks.iterrows():
        source_parts.append(
            f"[{paper_id}] Section: {chunk['section']}\n"
            f"Chunk ID: {chunk['chunk_id']}\n"
            f"{chunk['text']}"
        )

    retrieved_text = "\n\n".join(source_parts)

    # Build the two-shot prompt.
    prompt = build_summarization_prompt(question, retrieved_text)

    output_path = output_folder / f"{paper_id}_prompt.txt"
    output_path.write_text(prompt, encoding="utf-8")

    print("Prepared:", output_path)
    print("Source chunks:", len(selected_chunks))

print("All available test prompts prepared!")