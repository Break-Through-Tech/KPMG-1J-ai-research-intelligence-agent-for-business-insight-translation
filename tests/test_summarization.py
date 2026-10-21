
# my idea: Use our two-shot prompt with Groq to generate
# summaries for three research papers and save the results.

import sys
import os
from pathlib import Path
from openai import OpenAI

# Find the project root since this file is inside the tests folder.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.summarization.prompts import SUMMARIZATION_SYSTEM_PROMPT

# Connect to Groq using the API key stored in PowerShell.
client = OpenAI(
    api_key=os.environ["GROQ_API_KEY"],
    base_url="https://api.groq.com/openai/v1"
)

model_name = "openai/gpt-oss-120b"

# Prepared prompts are stored in the main summarization folder.
prompt_folder = PROJECT_ROOT / "reports" / "summarization"

# Save generated summaries in the v2 results folder.
output_folder = prompt_folder / "summarization_prompt_v2_results"
output_folder.mkdir(parents=True, exist_ok=True)

paper_ids = [
    "2609.38043v1",
    "2609.38070v1",
    "2609.38166v1"
]

for paper_id in paper_ids:

    prompt_path = prompt_folder / f"{paper_id}_prompt.txt"
    summary_path = output_folder / f"{paper_id}_summary.md"

    # Read the prepared two-shot prompt.
    prompt = prompt_path.read_text(encoding="utf-8")

    print("Generating summary for:", paper_id)

    # Ask Groq to summarize the retrieved research content.
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": SUMMARIZATION_SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.1,
        max_completion_tokens=1500
    )

    summary = response.choices[0].message.content

    if summary is None or summary.strip() == "":
        print("No summary returned for:", paper_id)
    else:
        # Save the actual generated summary.
        summary_path.write_text(summary, encoding="utf-8")
        print("Saved:", summary_path)

print("Summarization tests finished!")