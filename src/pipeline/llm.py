# LLM client used to generate summaries from retrieved research
#
# Groq is the default and uses the same model and settings as Lakshmee's
# summarization testing (src/summarization/README.md), so results stay
# comparable. Gemini is available through Google's OpenAI-compatible
# endpoint for when the Groq daily token limit runs out.

import os
import re
import time


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
        "model": "gemini-3.8-flash",
    },
}

DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL = PROVIDERS[DEFAULT_PROVIDER]["model"]

# Waits (seconds) when a rate limit error doesn't say how long to wait
BACKOFF_SECONDS = [15, 30, 60, 120, 120]

# Phrases in a rate limit error that mean the daily quota is used up,
# which waiting a few minutes won't fix
# (Groq: "tokens per day (TPD)", Gemini: "...RequestsPerDayPerProject...")
DAILY_LIMIT_MARKERS = ["per day", "TPD", "RPD", "PerDay"]


def is_daily_limit(message):
    return any(marker.lower() in message.lower() for marker in DAILY_LIMIT_MARKERS)


def retry_wait_seconds(error, attempt):
    """
    How long to wait before retrying a rate limited request: the provider's
    retry-after header, else the wait named in the message (Groq: "Please try
    again in 1m2.5s", Gemini: "retryDelay': '34s'"), else a fixed backoff.
    """
    response = getattr(error, "response", None)
    header = response.headers.get("retry-after") if response is not None else None

    try:
        return float(header)
    except (TypeError, ValueError):
        pass

    message = str(error)

    match = (
        re.search(r"(?:try again|retry) in (?:(\d+)m)?([\d.]+)s", message)
        or re.search(r"retryDelay\W+(?:(\d+)m)?([\d.]+)s", message)
    )

    if match:
        minutes = int(match.group(1) or 0)
        return minutes * 60 + float(match.group(2))

    return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]


class LLM:

    def __init__(
        self,
        provider=DEFAULT_PROVIDER,
        model=None,
        temperature=0.1,
        max_tokens=4096,
        reasoning_effort="low",
        max_retries=5,
        sleep=time.sleep
    ):
        if provider not in PROVIDERS:
            raise ValueError(
                f"Unknown provider {provider!r}, choose from {', '.join(PROVIDERS)}"
            )

        settings = PROVIDERS[provider]

        self.provider = provider
        self.model = model or settings["model"]
        self.temperature = temperature
        # gpt-oss and Gemini are reasoning models: their hidden reasoning
        # counts toward max_tokens, so 1500 cut off most 5-paper summaries
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort

        # "length" means the response hit max_tokens and was cut off
        self.last_finish_reason = None

        # Free tiers limit tokens/requests per minute, so a rate limited
        # request is retried after a wait (sleep is swappable for tests)
        self.max_retries = max_retries
        self.sleep = sleep

        key_variable = settings["key_variable"]
        api_key = os.environ.get(key_variable)

        if not api_key:
            raise RuntimeError(
                f"{key_variable} is not set. Export it before running "
                f"the pipeline, e.g. export {key_variable}=..."
            )

        # Imported here so the rest of the pipeline works without openai installed
        from openai import OpenAI

        # The client's own retries are turned off so generate() controls the waits
        self.client = OpenAI(
            api_key=api_key,
            base_url=settings["base_url"],
            max_retries=0
        )

    def generate(self, system_prompt, user_prompt):
        """
        Send one system + user prompt and return the response text.
        """

        response = self._create_with_retries(system_prompt, user_prompt)

        self.last_finish_reason = response.choices[0].finish_reason

        text = response.choices[0].message.content

        if text is None or not text.strip():
            raise RuntimeError("The LLM returned an empty response")

        return text.strip()

    def _create_with_retries(self, system_prompt, user_prompt):
        """
        Call the API, waiting and retrying on per-minute rate limits.
        A daily limit stops at once, since waiting won't help.
        """
        from openai import RateLimitError

        for attempt in range(self.max_retries + 1):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=self.temperature,
                    max_completion_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort
                )

            except RateLimitError as error:
                if is_daily_limit(str(error)):
                    raise RuntimeError(
                        f"The daily {self.provider} limit for this API key is used up. "
                        "Rerun later (benchmark runs continue where they stopped), "
                        "use another key, or switch with --provider."
                    ) from error

                if attempt == self.max_retries:
                    raise

                wait = retry_wait_seconds(error, attempt) + 1
                print(f"Rate limited, waiting {wait:.0f}s "
                      f"(attempt {attempt + 1}/{self.max_retries})")
                self.sleep(wait)


# Earlier name, kept so existing code and notebooks keep working
GroqLLM = LLM
