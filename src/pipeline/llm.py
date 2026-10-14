# LLM client used to generate summaries from retrieved research
#
# Uses the same Groq model and settings as Lakshmee's summarization
# testing (src/summarization/README.md), so results stay comparable.

import os


DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqLLM:

    def __init__(
        self,
        model=DEFAULT_MODEL,
        temperature=0.1,
        max_tokens=1500
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        api_key = os.environ.get("GROQ_API_KEY")

        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Export it before running "
                "the pipeline, e.g. export GROQ_API_KEY=..."
            )

        # Imported here so the rest of the pipeline works without openai installed
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)

    def generate(self, system_prompt, user_prompt):
        """
        Send one system + user prompt and return the response text.
        """

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=self.temperature,
            max_completion_tokens=self.max_tokens
        )

        text = response.choices[0].message.content

        if text is None or not text.strip():
            raise RuntimeError("The LLM returned an empty response")

        return text.strip()
