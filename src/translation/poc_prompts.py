# Prompt and parser for the POC Starter (src/app/poc_starter.py): one use case
# plus a few answers from the team becomes a short pilot checklist.
#
# Like the industry application prompt, the checklist is a proposal. It is built
# from the saved research summary only, and must not claim the research tested
# the pilot.

import re

MIN_STEPS = 3
MAX_STEPS = 12
MAX_STEP_CHARS = 300

POC_CHECKLIST_SYSTEM_PROMPT = """Write a pilot checklist for a team in the target
industry who want to try one use case. Treat the saved research summary as the
only source for what the research says, and base the steps on the approach it
describes. Present every step as a proposal. Never say the research tested this
pilot, and never invent results, numbers or papers. If the summary gives too
little detail for a step, make that step about finding out.

Use the team's answers to fit the checklist to their people, tools, timeline,
success measure and biggest worry. If an answer says "Not answered", write one
step about deciding it. Mark anything you had to assume with "(assumed)".

Write 8 to 10 steps in the order the team would do them. Cover: getting access to
the records or tools, measuring how the work is done today, a small first run,
who reviews the output and records corrections, the success measure, a safeguard
for the biggest worry, and a final step to expand, change or stop the pilot.

Use plain, professional language. Start each step with a verb and keep it under
25 words. Write one step per line, each starting with "- ". Do not write
headings, an introduction or a closing."""


def build_poc_checklist_prompt(summary, industry, use_case, answers):
    """answers: {question: answer}; a blank answer is sent as "Not answered"."""
    lines = [f"Target industry: {industry}", f"Use case: {use_case}", "", "Team answers:"]

    for question, answer in answers.items():
        lines.append(f"- {question} {answer.strip() or 'Not answered'}")

    lines += ["", "Saved research summary:", summary]

    return "\n".join(lines)


# "- step", "* step", "1. step", "1) step", "- [ ] step" and "- [x] step"
STEP_LINE = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+(?:\[[ xX]?\]\s*)?(.+?)\s*$")


def parse_checklist(text):
    """
    Turn the model's reply into [{"text", "done"}] for a pilot plan. Lines that
    aren't list items (a stray heading or introduction) are ignored. Raises a
    ValueError, which the app shows to the user, if there are too few steps.
    """
    steps = []

    for line in text.splitlines():
        match = STEP_LINE.match(line)
        if not match:
            continue

        step = match.group(1).replace("**", "").replace("__", "").strip()
        if step:
            steps.append(step[:MAX_STEP_CHARS])

    if len(steps) < MIN_STEPS:
        raise ValueError("The model didn't return a usable checklist. Please try again.")

    return [{"text": step, "done": False} for step in steps[:MAX_STEPS]]
