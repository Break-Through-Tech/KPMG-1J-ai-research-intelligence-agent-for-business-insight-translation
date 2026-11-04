# POC Starter: the one route that needs the LLM.
#
# POST /api/briefs/{brief_id}/pilot-checklist turns one use case and a few
# answers into a pilot checklist (one LLM call, nothing is saved). The page then
# saves the plan with the pilot plan routes in server.py, which cost no LLM calls
# to save, open, tick or edit.
#
# This lives in its own file so it never collides with other changes to
# server.py. server.py only imports add_poc_routes and calls it once.

from fastapi import HTTPException
from pydantic import BaseModel

from src.translation.poc_prompts import (
    POC_CHECKLIST_SYSTEM_PROMPT,
    build_poc_checklist_prompt,
    parse_checklist,
)

INDUSTRY_LIMIT = 120    # same as NAME_LIMIT in server.py
USE_CASE_LIMIT = 300
ANSWER_LIMIT = 300
MAX_ANSWERS = 10


class PocChecklistRequest(BaseModel):
    industry: str
    use_case: str
    # POC Starter question -> the user's answer (may be blank)
    answers: dict[str, str] = {}


def add_poc_routes(app, load, run_llm, llm):
    """
    load:    server.py's load(brief_id), which raises a 404 for an unknown brief
    run_llm: server.py's run_llm(step), which turns LLM errors into messages
    """

    @app.post("/api/briefs/{brief_id}/pilot-checklist")
    def pilot_checklist(brief_id: str, request: PocChecklistRequest):
        record = load(brief_id)

        industry = request.industry.strip()
        use_case = request.use_case.strip()

        if not industry:
            raise HTTPException(400, "Please choose an industry.")
        if len(industry) > INDUSTRY_LIMIT:
            raise HTTPException(400, f"Industry is too long (at most {INDUSTRY_LIMIT} characters).")
        if not use_case:
            raise HTTPException(400, "Please pick or write a use case.")
        if len(use_case) > USE_CASE_LIMIT:
            raise HTTPException(400, f"The use case is too long (at most {USE_CASE_LIMIT} characters).")
        if len(request.answers) > MAX_ANSWERS:
            raise HTTPException(400, f"Too many answers (at most {MAX_ANSWERS}).")

        answers = {}
        for question, answer in request.answers.items():
            if len(answer.strip()) > ANSWER_LIMIT:
                raise HTTPException(400, f"An answer is too long (at most {ANSWER_LIMIT} characters).")
            answers[question.strip()] = answer.strip()

        if not record["sources"] or not record["briefs"]:
            raise HTTPException(400, "This brief has no research summary to build a pilot from.")

        prompt = build_poc_checklist_prompt(record["summary"], industry, use_case, answers)

        # parse_checklist raises a ValueError for an unusable reply, which run_llm
        # turns into a 400 with its message
        checklist = run_llm(lambda: parse_checklist(llm.generate(POC_CHECKLIST_SYSTEM_PROMPT, prompt)))

        return {"checklist": checklist}
