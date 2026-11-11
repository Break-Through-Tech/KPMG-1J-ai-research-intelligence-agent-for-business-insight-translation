# Web UI for consultants: ask a question, get a cited business brief.
#
# python -m src.app                      (Groq, needs GROQ_API_KEY)
# python -m src.app --provider nvidia    (needs NVIDIA_API_KEY, free at build.nvidia.com)
# python -m src.app --provider gemini    (needs GEMINI_API_KEY)
# then open http://localhost:8000
#
# LLM calls per action: ask = 2, rewrite for another audience = 1,
# follow-up question = 1, market scan = 1 (plus SEC EDGAR requests),
# everything else (open, approve, request changes, copy link, copy for
# email/Slack, projects) = 0.
#
# Projects hold a client's details and a list of briefs (a brief can be in
# several projects). Asking inside a project adds the client details to the
# brief step only; retrieval and the research summary are unchanged.
#
# Industry adaptations (a brief applied to one industry), pilot plans (built
# from one use case of an adaptation) and comments (on a brief, adaptation or
# pilot plan) are saved as JSON files too, and cost no LLM calls to save,
# open, edit or delete.

import argparse
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.market.edgar import edgar_from_env
from src.pipeline.pipeline import answer_followup, answer_query, translate_summary
from src.translation.prompts import (
    AUDIENCES,
    DEFAULT_AUDIENCE,
    INDUSTRY_APPLICATION_SYSTEM_PROMPT,
    build_industry_application_prompt,
    format_client_context,
)

from .checks import run_checks
from .market import add_market_routes
from .poc_starter import add_poc_routes
from .store import (
    AdaptationStore,
    BriefStore,
    CommentStore,
    MarketScanStore,
    PilotPlanStore,
    ProjectStore,
)

STATIC_DIR = Path(__file__).parent / "static"

STATUSES = {"draft", "approved", "changes"}

# Page files that get a version in their link, so browsers never mix old and new
STATIC_FILES = ("app.css", "app.js", "poc.css", "poc.js", "market.css", "market.js")

PROJECT_STATUSES = {"active", "archived"}

# Longest value accepted for each project field
PROJECT_FIELDS = {"name": 120, "client": 120, "industry": 120, "objective": 1000, "notes": 4000}

# Longest text accepted for adaptations, pilot plans and comments
NAME_LIMIT = 120          # industry, author, created_by, plan title
TEXT_LIMIT = 4000         # one comment, one use case, one answer, one checklist item
MAX_ITEMS = 50            # entries in one list (use cases, checklist, answers...)
MAX_FIELD_BYTES = 50_000  # one list field saved as JSON

# What a comment can be attached to
COMMENT_TARGETS = {"brief", "adaptation", "pilot_plan"}

# More papers make the summary prompt longer and slower without better briefs
MAX_PAPERS = 5

# Benchmark questions offered as one-click examples on the ask page
EXAMPLE_QUERY_IDS = ["Q11", "Q13", "Q12", "Q19"]


class AskRequest(BaseModel):
    question: str
    audience: str = DEFAULT_AUDIENCE
    top_k: int = 5
    # optional filters: "YYYY-MM-DD" dates and arXiv primary categories
    since: str | None = None
    until: str | None = None
    categories: list[str] = []
    # ask inside a project: the brief is tailored to its client and saved there
    project_id: str | None = None


class IndustryApplicationRequest(BaseModel):
    industry: Literal[
        "Healthcare",
        "Finance",
        "Construction & Real Estate",
        "Government & Public Services",
    ]


class ProjectRequest(BaseModel):
    name: str | None = None
    client: str | None = None
    industry: str | None = None
    objective: str | None = None
    notes: str | None = None
    status: str | None = None


class ProjectBriefRequest(BaseModel):
    brief_id: str


class AdaptationRequest(BaseModel):
    industry: str | None = None
    # Text entries or small objects, whatever the industry prompt returns
    use_cases: list[str | dict] | None = None
    constraints: list[str | dict] | None = None
    considerations: list[str | dict] | None = None
    created_by: str | None = None


class ChecklistItem(BaseModel):
    text: str
    done: bool = False


class PilotPlanRequest(BaseModel):
    title: str | None = None
    use_case: str | dict | None = None
    # POC Starter question -> the user's answer
    answers: dict[str, str] | None = None
    checklist: list[ChecklistItem] | None = None
    created_by: str | None = None


class CommentRequest(BaseModel):
    target_type: str
    target_id: str
    author: str
    text: str


class FollowupRequest(BaseModel):
    question: str


class StatusRequest(BaseModel):
    status: str
    note: str = ""


class RewriteRequest(BaseModel):
    audience: str


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def brief_entry(result, insight):
    return {
        "brief": insight["brief"],
        "truncated": insight["truncated"],
        "citation_check": insight["citation_check"],
        "checks": run_checks(result, insight),
        "created_at": now(),
    }


def create_app(retriever, llm, store, corpus=None, examples=None, projects=None,
               adaptations=None, pilot_plans=None, comments=None, compressor=None,
               compact_prompt=False, market_scans=None, edgar=None):
    """
    retriever: anything with search(query, top_k) (see src/pipeline/pipeline.py)
    llm:       anything with generate(system_prompt, user_prompt)
    store:     a BriefStore
    projects:  a ProjectStore (defaults to a "projects" folder next to the briefs)
    adaptations, pilot_plans, comments: an AdaptationStore, PilotPlanStore and
               CommentStore (each defaults to a folder next to the briefs)
    corpus:    {"papers": int, "first_date": str, "last_date": str} for the header
    examples:  example questions for the ask page
    compressor: optional ContextCompressor that shortens the paper text before
               the summary call (src/pipeline/compress.py)
    compact_prompt: use the shorter summarization instructions
    market_scans, edgar: a MarketScanStore and an EdgarClient for the Market tab
               (src/app/market.py); edgar is None when SEC_USER_AGENT isn't set
    """

    app = FastAPI(title="Research Insight Agent")

    if projects is None:
        projects = ProjectStore(Path(store.directory).parent / "ui_projects")
    if adaptations is None:
        adaptations = AdaptationStore(Path(store.directory).parent / "ui_adaptations")
    if pilot_plans is None:
        pilot_plans = PilotPlanStore(Path(store.directory).parent / "ui_pilot_plans")
    if comments is None:
        comments = CommentStore(Path(store.directory).parent / "ui_comments")
    if market_scans is None:
        market_scans = MarketScanStore(Path(store.directory).parent / "ui_market_scans")

    # Adaptations, pilot plans and comments are read and rewritten as a whole too
    storage_lock = threading.Lock()

    # Project files are read and rewritten as a whole, so one change at a time
    project_lock = threading.Lock()

    # The retriever and LLM are shared, so run one pipeline call at a time
    pipeline_lock = threading.Lock()

    def check_audience(audience):
        if audience not in AUDIENCES:
            raise HTTPException(400, f"Unknown audience {audience!r}")

    def load(brief_id):
        try:
            return store.load(brief_id)
        except KeyError:
            raise HTTPException(404, "Brief not found")

    def with_projects(record):
        """The brief plus the projects it's in, for the brief page."""
        return {**record, "projects": projects.projects_for(record["id"])}

    def load_project(project_id):
        try:
            return projects.load(project_id)
        except KeyError:
            raise HTTPException(404, "Project not found")

    def apply_project_fields(project, request):
        for field, limit in PROJECT_FIELDS.items():
            value = getattr(request, field)
            if value is None:
                continue
            value = value.strip()
            if len(value) > limit:
                raise HTTPException(400, f"{field.capitalize()} is too long (at most {limit} characters).")
            project[field] = value

        if request.status is not None:
            if request.status not in PROJECT_STATUSES:
                raise HTTPException(400, f"Unknown project status {request.status!r}")
            project["status"] = request.status

        if not project.get("name"):
            raise HTTPException(400, "Please give the project a name.")

        project["updated_at"] = now()

    def run_llm(step):
        """Run a pipeline step and turn its errors into messages the page can show."""
        try:
            with pipeline_lock:
                return step()
        except ValueError as error:
            raise HTTPException(400, str(error))
        except RuntimeError as error:
            # e.g. the daily API limit is used up
            raise HTTPException(503, str(error))
        except Exception as error:
            raise HTTPException(502, f"The LLM request failed: {error}")

    @app.get("/api/info")
    def info():
        return {
            "corpus": corpus or {},
            "provider": getattr(llm, "provider", ""),
            "model": getattr(llm, "model", ""),
            "audiences": list(AUDIENCES),
            "default_audience": DEFAULT_AUDIENCE,
            "examples": examples or [],
        }

    @app.post("/api/ask")
    def ask(request: AskRequest):
        question = request.question.strip()
        if not question:
            raise HTTPException(400, "Please type a question.")
        check_audience(request.audience)
        if not 1 <= request.top_k <= MAX_PAPERS:
            raise HTTPException(400, f"Papers per answer must be between 1 and {MAX_PAPERS}.")

        filters = {
            "since": request.since or None,
            "until": request.until or None,
            "categories": request.categories,
        }
        if not any(filters.values()):
            filters = None

        project = load_project(request.project_id) if request.project_id else None
        client = format_client_context(project) or None

        result = run_llm(lambda: answer_query(
            question, retriever, llm, top_k=request.top_k,
            translate=True, audience=request.audience, filters=filters,
            client=client, compressor=compressor, compact_prompt=compact_prompt,
        ))

        insight = result.pop("business_insight")

        record = {
            "id": store.new_id(),
            "created_at": now(),
            "query": question,
            "audience": request.audience,
            "top_k": request.top_k,
            "provider": getattr(llm, "provider", ""),
            "model": getattr(llm, "model", ""),
            "status": "draft",
            "note": "",
            "filters": filters or {},
            **result,
            "briefs": {},
            "followups": [],
        }

        if project:
            # The exact client text is kept, so rewrites and follow-ups stay
            # consistent even if the project's details change later
            record["asked_in"] = project["id"]
            record["client_context"] = client or ""

        if insight:
            record["briefs"][request.audience] = brief_entry(result, insight)

        store.save(record)

        if project:
            with project_lock:
                project = projects.load(project["id"])
                project.setdefault("brief_ids", []).insert(0, record["id"])
                project["updated_at"] = now()
                projects.save(project)

        return with_projects(record)

    @app.get("/api/briefs")
    def list_briefs(limit: int = 20):
        # how many market scans each brief has, for the Library filter
        scan_counts = market_scans.counts()
        return [
            {**row, "market_scans": scan_counts.get(row["id"], 0)}
            for row in store.list(limit=max(1, min(limit, 500)))
        ]

    @app.get("/api/briefs/{brief_id}")
    def get_brief(brief_id: str):
        return with_projects(load(brief_id))

    @app.post("/api/briefs/{brief_id}/status")
    def set_status(brief_id: str, request: StatusRequest):
        if request.status not in STATUSES:
            raise HTTPException(400, f"Unknown status {request.status!r}")

        record = load(brief_id)
        record["status"] = request.status
        record["note"] = request.note.strip()
        record["reviewed_at"] = now()
        return with_projects(store.save(record))

    @app.post("/api/briefs/{brief_id}/rewrite")
    def rewrite(brief_id: str, request: RewriteRequest):
        check_audience(request.audience)
        record = load(brief_id)

        if not record["sources"]:
            raise HTTPException(400, "No research was found for this question, so there is nothing to rewrite.")

        # Reuses the saved summary, so this is one LLM call, not two
        insight = run_llm(lambda: translate_summary(
            record["query"], record["summary"], record["sources"], llm, request.audience,
            record.get("client_context") or None,
        ))

        record["briefs"][request.audience] = brief_entry(record, insight)
        record["audience"] = request.audience
        record["status"] = "draft"
        record["note"] = ""
        return with_projects(store.save(record))

    @app.post("/api/briefs/{brief_id}/followup")
    def followup(brief_id: str, request: FollowupRequest):
        question = request.question.strip()
        if not question:
            raise HTTPException(400, "Please type a follow-up question.")

        record = load(brief_id)
        entry = record["briefs"].get(record["audience"])

        if not record["sources"] or not entry:
            raise HTTPException(400, "This question has no research summary to answer from.")

        # Answers from the saved summary, so this is one LLM call and no new search
        followups = record.setdefault("followups", [])
        answer = run_llm(lambda: answer_followup(
            record["query"], record["summary"], entry["brief"], record["sources"],
            question, llm, record["audience"], history=followups,
            client=record.get("client_context") or None,
        ))

        followups.append({**answer, "audience": record["audience"], "created_at": now()})
        return with_projects(store.save(record))

    @app.post("/api/briefs/{brief_id}/industry-application")
    def industry_application(brief_id: str, request: IndustryApplicationRequest):
        record = load(brief_id)
        if not record["sources"] or not record["briefs"]:
            raise HTTPException(400, "This brief has no research summary to adapt.")

        prompt = build_industry_application_prompt(record["summary"], request.industry)
        application = run_llm(lambda: llm.generate(INDUSTRY_APPLICATION_SYSTEM_PROMPT, prompt))
        return {"application": application}

    # ---------- projects ----------

    @app.get("/api/projects")
    def list_projects():
        return projects.list()

    @app.post("/api/projects")
    def create_project(request: ProjectRequest):
        project = {
            "id": projects.new_id(),
            "created_at": now(),
            "name": "", "client": "", "industry": "", "objective": "", "notes": "",
            "status": "active",
            "brief_ids": [],
        }
        apply_project_fields(project, request)
        return projects.save(project)

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: str):
        project = load_project(project_id)
        return {**project, "briefs": store.summaries(project.get("brief_ids", []))}

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: str, request: ProjectRequest):
        with project_lock:
            project = load_project(project_id)
            apply_project_fields(project, request)
            projects.save(project)
        return get_project(project_id)

    @app.post("/api/projects/{project_id}/briefs")
    def add_project_brief(project_id: str, request: ProjectBriefRequest):
        load(request.brief_id)  # 404 if the brief doesn't exist
        with project_lock:
            project = load_project(project_id)
            ids = project.setdefault("brief_ids", [])
            if request.brief_id not in ids:
                ids.insert(0, request.brief_id)
                project["updated_at"] = now()
                projects.save(project)
        return get_project(project_id)

    @app.delete("/api/projects/{project_id}/briefs/{brief_id}")
    def remove_project_brief(project_id: str, brief_id: str):
        # Only the link is removed; the brief itself stays in the Library
        with project_lock:
            project = load_project(project_id)
            ids = project.get("brief_ids", [])
            if brief_id in ids:
                ids.remove(brief_id)
                project["updated_at"] = now()
                projects.save(project)
        return get_project(project_id)

    # ---------- industry adaptations, pilot plans, comments ----------

    def load_from(kind_store, record_id, label):
        try:
            return kind_store.load(record_id)
        except KeyError:
            raise HTTPException(404, f"{label} not found")

    def clean_name(field, value):
        value = (value or "").strip()
        if len(value) > NAME_LIMIT:
            raise HTTPException(400, f"{field} is too long (at most {NAME_LIMIT} characters).")
        return value

    def clean_text(field, value, limit=TEXT_LIMIT):
        value = (value or "").strip()
        if len(value) > limit:
            raise HTTPException(400, f"{field} is too long (at most {limit} characters).")
        return value

    def clean_list(field, items):
        """Strip text entries, drop empty ones, and keep the field a sensible size."""
        if len(items) > MAX_ITEMS:
            raise HTTPException(400, f"Too many {field} (at most {MAX_ITEMS}).")
        cleaned = []
        for item in items:
            if isinstance(item, str):
                item = clean_text(f"One of the {field}", item)
                if not item:
                    continue
            cleaned.append(item)
        if len(json.dumps(cleaned, ensure_ascii=False)) > MAX_FIELD_BYTES:
            raise HTTPException(400, f"The {field} are too long.")
        return cleaned

    def comments_on(target_type, target_id):
        return comments.list(target_type, target_id)

    def target_exists(target_type, target_id):
        kind_store, label = {
            "brief": (store, "Brief"),
            "adaptation": (adaptations, "Adaptation"),
            "pilot_plan": (pilot_plans, "Pilot plan"),
        }[target_type]
        load_from(kind_store, target_id, label)

    def delete_comments_on(target_type, target_id):
        for comment in comments_on(target_type, target_id):
            try:
                comments.delete(comment["id"])
            except KeyError:
                pass

    def apply_adaptation_fields(adaptation, request):
        if request.industry is not None:
            adaptation["industry"] = clean_name("Industry", request.industry)
        for field in ("use_cases", "constraints", "considerations"):
            value = getattr(request, field)
            if value is not None:
                adaptation[field] = clean_list(field.replace("_", " "), value)
        if request.created_by is not None:
            adaptation["created_by"] = clean_name("Created by", request.created_by)
        if not adaptation.get("industry"):
            raise HTTPException(400, "Please choose an industry.")
        adaptation["updated_at"] = now()

    def full_adaptation(adaptation):
        """The adaptation plus its pilot plans and comments, for its page."""
        return {
            **adaptation,
            "pilot_plans": pilot_plans.list(adaptation_id=adaptation["id"]),
            "comments": comments_on("adaptation", adaptation["id"]),
        }

    def apply_pilot_fields(plan, request):
        if request.title is not None:
            plan["title"] = clean_name("Title", request.title)
        if request.use_case is not None:
            plan["use_case"] = (clean_text("Use case", request.use_case)
                                if isinstance(request.use_case, str) else request.use_case)
        if request.answers is not None:
            if len(request.answers) > MAX_ITEMS:
                raise HTTPException(400, f"Too many answers (at most {MAX_ITEMS}).")
            plan["answers"] = {
                clean_text("A question", q, NAME_LIMIT * 4): clean_text("An answer", a)
                for q, a in request.answers.items()
            }
        if request.checklist is not None:
            if len(request.checklist) > MAX_ITEMS:
                raise HTTPException(400, f"Too many checklist items (at most {MAX_ITEMS}).")
            plan["checklist"] = [
                {"text": text, "done": item.done}
                for item in request.checklist
                if (text := clean_text("A checklist item", item.text))
            ]
        if request.created_by is not None:
            plan["created_by"] = clean_name("Created by", request.created_by)
        if not plan.get("use_case"):
            raise HTTPException(400, "Please choose a use case for the pilot plan.")
        plan["updated_at"] = now()

    def full_pilot_plan(plan):
        return {**plan, "comments": comments_on("pilot_plan", plan["id"])}

    # Adaptations

    @app.get("/api/adaptations")
    def list_adaptations(brief_id: str | None = None, industry: str | None = None):
        return adaptations.list(brief_id=brief_id, industry=industry)

    @app.get("/api/briefs/{brief_id}/adaptations")
    def list_brief_adaptations(brief_id: str):
        load(brief_id)  # 404 if the brief doesn't exist
        return adaptations.list(brief_id=brief_id)

    @app.post("/api/briefs/{brief_id}/adaptations")
    def create_adaptation(brief_id: str, request: AdaptationRequest):
        brief = load(brief_id)
        adaptation = {
            "id": adaptations.new_id(),
            "brief_id": brief_id,
            "query": brief.get("query", ""),
            "created_at": now(),
            "created_by": "",
            "industry": "",
            "use_cases": [],
            "constraints": [],
            "considerations": [],
        }
        apply_adaptation_fields(adaptation, request)
        return full_adaptation(adaptations.save(adaptation))

    @app.get("/api/adaptations/{adaptation_id}")
    def get_adaptation(adaptation_id: str):
        return full_adaptation(load_from(adaptations, adaptation_id, "Adaptation"))

    @app.put("/api/adaptations/{adaptation_id}")
    def update_adaptation(adaptation_id: str, request: AdaptationRequest):
        with storage_lock:
            adaptation = load_from(adaptations, adaptation_id, "Adaptation")
            apply_adaptation_fields(adaptation, request)
            adaptations.save(adaptation)
        return full_adaptation(adaptation)

    @app.delete("/api/adaptations/{adaptation_id}")
    def delete_adaptation(adaptation_id: str):
        # Its pilot plans and all their comments go with it
        with storage_lock:
            load_from(adaptations, adaptation_id, "Adaptation")
            for plan in pilot_plans.list(adaptation_id=adaptation_id):
                delete_comments_on("pilot_plan", plan["id"])
                pilot_plans.delete(plan["id"])
            delete_comments_on("adaptation", adaptation_id)
            adaptations.delete(adaptation_id)
        return {"deleted": adaptation_id}

    # Pilot plans

    @app.get("/api/pilot-plans")
    def list_pilot_plans(adaptation_id: str | None = None, brief_id: str | None = None):
        return pilot_plans.list(adaptation_id=adaptation_id, brief_id=brief_id)

    @app.get("/api/adaptations/{adaptation_id}/pilot-plans")
    def list_adaptation_pilot_plans(adaptation_id: str):
        load_from(adaptations, adaptation_id, "Adaptation")
        return pilot_plans.list(adaptation_id=adaptation_id)

    @app.post("/api/adaptations/{adaptation_id}/pilot-plans")
    def create_pilot_plan(adaptation_id: str, request: PilotPlanRequest):
        adaptation = load_from(adaptations, adaptation_id, "Adaptation")
        plan = {
            "id": pilot_plans.new_id(),
            "adaptation_id": adaptation_id,
            "brief_id": adaptation.get("brief_id"),
            "industry": adaptation.get("industry", ""),
            "created_at": now(),
            "created_by": "",
            "title": "",
            "use_case": "",
            "answers": {},
            "checklist": [],
        }
        apply_pilot_fields(plan, request)
        return full_pilot_plan(pilot_plans.save(plan))

    @app.get("/api/pilot-plans/{plan_id}")
    def get_pilot_plan(plan_id: str):
        return full_pilot_plan(load_from(pilot_plans, plan_id, "Pilot plan"))

    @app.put("/api/pilot-plans/{plan_id}")
    def update_pilot_plan(plan_id: str, request: PilotPlanRequest):
        # Fields left out keep their value, so ticking one checklist box can
        # send just the checklist
        with storage_lock:
            plan = load_from(pilot_plans, plan_id, "Pilot plan")
            apply_pilot_fields(plan, request)
            pilot_plans.save(plan)
        return full_pilot_plan(plan)

    @app.delete("/api/pilot-plans/{plan_id}")
    def delete_pilot_plan(plan_id: str):
        with storage_lock:
            load_from(pilot_plans, plan_id, "Pilot plan")
            delete_comments_on("pilot_plan", plan_id)
            pilot_plans.delete(plan_id)
        return {"deleted": plan_id}

    # Comments

    @app.get("/api/comments")
    def list_comments(target_type: str, target_id: str):
        if target_type not in COMMENT_TARGETS:
            raise HTTPException(400, f"Unknown comment target {target_type!r}")
        return comments_on(target_type, target_id)

    @app.post("/api/comments")
    def create_comment(request: CommentRequest):
        if request.target_type not in COMMENT_TARGETS:
            raise HTTPException(400, f"Unknown comment target {request.target_type!r}")
        target_exists(request.target_type, request.target_id)
        author = clean_name("Author", request.author)
        text = clean_text("Comment", request.text)
        if not author:
            raise HTTPException(400, "Please give the comment's author.")
        if not text:
            raise HTTPException(400, "Please type a comment.")
        comment = {
            "id": comments.new_id(),
            "target_type": request.target_type,
            "target_id": request.target_id,
            "author": author,
            "text": text,
            # Microseconds, so two comments in the same second keep their order
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        }
        return comments.save(comment)

    @app.delete("/api/comments/{comment_id}")
    def delete_comment(comment_id: str):
        try:
            comments.delete(comment_id)
        except KeyError:
            raise HTTPException(404, "Comment not found")
        return {"deleted": comment_id}

    # POC Starter: turns a use case into a pilot checklist (src/app/poc_starter.py)
    add_poc_routes(app, load, run_llm, llm)

    # Market scans: SEC filings + one LLM call (src/app/market.py)
    add_market_routes(app, load, run_llm, llm, market_scans, edgar, projects, now, STATUSES)

    @app.get("/")
    def index():
        # Versioned asset links, so a browser never pairs a new page with an old
        # cached app.css or app.js after the code changes
        version = static_version()
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for name in STATIC_FILES:
            html = html.replace(f'/static/{name}"', f'/static/{name}?v={version}"')
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    @app.middleware("http")
    async def revalidate_static(request, call_next):
        # Browsers may keep files with no cache header; make them check for a newer one
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


def static_version():
    """Changes whenever one of the page's CSS or JS files changes on disk."""
    return str(int(max((STATIC_DIR / name).stat().st_mtime for name in STATIC_FILES)))


def corpus_info(papers_path):
    import pandas as pd

    import pyarrow.parquet as pq

    columns = ["published_date"]
    if "primary_category" in pq.read_schema(papers_path).names:
        columns.append("primary_category")

    papers = pd.read_parquet(papers_path, columns=columns)
    dates = pd.to_datetime(papers["published_date"])

    # topics the ask page can filter by, most papers first
    categories = (
        papers["primary_category"].value_counts().items()
        if "primary_category" in papers else []
    )

    return {
        "papers": int(len(dates)),
        "first_date": dates.min().date().isoformat(),
        "last_date": dates.max().date().isoformat(),
        "categories": [{"id": c, "papers": int(n)} for c, n in categories],
    }


def load_examples(benchmark_path):
    import pandas as pd

    try:
        queries = pd.read_csv(benchmark_path).set_index("query_id")
    except (OSError, KeyError):
        return []

    return [queries.loc[q, "query"] for q in EXAMPLE_QUERY_IDS if q in queries.index]


def main():
    from src.pipeline.llm import DEFAULT_PROVIDER, LLM, PROVIDERS

    parser = argparse.ArgumentParser(description="Run the consultant web UI")
    parser.add_argument("--provider", choices=list(PROVIDERS), default=DEFAULT_PROVIDER)
    parser.add_argument("--model")
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high", "none"], default="low",
                        help="none leaves the setting out, for models that don't accept it")
    parser.add_argument("--papers", default="data/papers_clean.parquet")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--benchmark", default="evaluation/benchmark_queries.csv")
    parser.add_argument("--briefs-dir", default="data/ui_briefs")
    parser.add_argument("--projects-dir", default="data/ui_projects")
    parser.add_argument("--adaptations-dir", default="data/ui_adaptations")
    parser.add_argument("--pilot-plans-dir", default="data/ui_pilot_plans")
    parser.add_argument("--comments-dir", default="data/ui_comments")
    parser.add_argument("--market-scans-dir", default="data/ui_market_scans")
    parser.add_argument("--compress", action="store_true",
                        help="shorten the retrieved passages before the summary call (src/pipeline/compress.py); "
                             "off by default because it made answers slower in testing")
    parser.add_argument("--context-budget", type=int, default=8000,
                        help="estimated tokens of paper text in the summary prompt")
    parser.add_argument("--compact-prompt", action="store_true",
                        help="shorter summarization instructions with one example")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Check the API key before the slow retriever startup
    llm = LLM(provider=args.provider, model=args.model, max_tokens=args.max_tokens,
              reasoning_effort=None if args.reasoning_effort == "none" else args.reasoning_effort)

    print("Loading the retriever and embedding model...")
    from src.rag.lance_retriever import LanceCombinedRetriever

    retriever = LanceCombinedRetriever(papers_path=args.papers, index_dir=args.index_dir)

    from src.pipeline.compress import CompressSettings, ContextCompressor

    compressor = None if not args.compress else ContextCompressor(
        retriever.embedder, CompressSettings(budget_tokens=args.context_budget))

    app = create_app(
        retriever,
        llm,
        BriefStore(args.briefs_dir),
        corpus=corpus_info(args.papers),
        examples=load_examples(args.benchmark),
        projects=ProjectStore(args.projects_dir),
        adaptations=AdaptationStore(args.adaptations_dir),
        pilot_plans=PilotPlanStore(args.pilot_plans_dir),
        comments=CommentStore(args.comments_dir),
        compressor=compressor,
        compact_prompt=args.compact_prompt,
        market_scans=MarketScanStore(args.market_scans_dir),
        edgar=edgar_from_env(),
    )

    import uvicorn

    print(f"Open http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
