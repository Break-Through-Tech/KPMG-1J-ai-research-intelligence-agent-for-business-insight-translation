# LLM client used to generate summaries from retrieved research
#
# Groq is the default and uses the same model and settings as Lakshmee's
# summarization testing (src/summarization/README.md), so results stay
# comparable. Gemini is available through Google's OpenAI-compatible
# endpoint for when the Groq daily token limit runs out.

import os


# provider -> where to send requests, which key to read, default model
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_variable": "GROQ_API_KEY",
        "model": "openai/gpt-oss-120b",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_variable": "GEMINI_API_KEY",
        "model": "gemini-2.5-flash",
    },
}

DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]["model"]


class LLM:

    def __init__(
        self,
        provider=DEFAULT_PROVIDER,
        model=None,
        temperature=0.1,
        max_tokens=4096,
        reasoning_effort="low"
    ):
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown provider {provider!r}, choose from {', '.join(PROVIDERS)}"
            )

        settings = PROVIDERS[provider]

        self.provider = provider
        self.model = model or settings["model"]
        self.temperature = temperature
        # gpt-oss and Gemini 2.5 are reasoning models: their hidden reasoning
        # counts toward max_tokens, so 1500 cut off most 5-paper summaries
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort

        # "length" means the response hit max_tokens and was cut off
        self.last_finish_reason = None

        key_variable = settings["key_variable"]
        api_key = os.environ.get(key_variable)

        if not api_key:
            raise RuntimeError(
                f"{key_variable} is not set. Export it before running "
                f"the pipeline, e.g. export {key_variable}=..."
            )

        # Imported here so the rest of the pipeline works without openai installed
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=settings["base_url"])

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
            max_completion_tokens=self.max_tokens,
            reasoning_effort=self.reasoning_effort
        )

        self.last_finish_reason = response.choices[0].finish_reason

        text = response.choices[0].message.content

        if text is None or not text.strip():
            raise RuntimeError("The LLM returned an empty response")

        return text.strip()


# Earlier name, kept so existing code and notebooks keep working
GroqLLM = LLM
