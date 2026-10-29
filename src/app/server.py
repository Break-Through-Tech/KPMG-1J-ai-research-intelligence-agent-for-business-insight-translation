# Web UI for consultants: ask a question, get a cited business brief.
#
# python -m src.app                      (Groq, needs GROQ_API_KEY)
# python -m src.app --provider nvidia    (needs NVIDIA_API_KEY, free at build.nvidia.com)
# python -m src.app --provider gemini    (needs GEMINI_API_KEY)
# then open http://localhost:8000
#
# LLM calls per action: ask = 2, rewrite for another audience = 1,
# follow-up question = 1, everything else (open, approve, request changes,
# copy link, copy for email/Slack, projects) = 0.
#
# Projects hold a client's details and a list of briefs (a brief can be in
# several projects). Asking inside a project adds the client details to the
# brief step only; retrieval and the research summary are unchanged.

import argparse
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.pipeline.pipeline import answer_followup, answer_query, translate_summary
from src.translation.prompts import AUDIENCES, DEFAULT_AUDIENCE, format_client_context

from .checks import run_checks
from .store import BriefStore, ProjectStore

STATIC_DIR = Path(__file__).parent / "static"

STATUSES = {"draft", "approved", "changes"}

PROJECT_STATUSES = {"active", "archived"}

# Longest value accepted for each project field
PROJECT_FIELDS = {"name": 120, "client": 120, "industry": 120, "objective": 1000, "notes": 4000}

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


class ProjectRequest(BaseModel):
    name: str | None = None
    client: str | None = None
    industry: str | None = None
    objective: str | None = None
    notes: str | None = None
    status: str | None = None


class ProjectBriefRequest(BaseModel):
    brief_id: str


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


def create_app(retriever, llm, store, corpus=None, examples=None, projects=None):
    """
    retriever: anything with search(query, top_k) (see src/pipeline/pipeline.py)
    llm:       anything with generate(system_prompt, user_prompt)
    store:     a BriefStore
    projects:  a ProjectStore (defaults to a "projects" folder next to the briefs)
    corpus:    {"papers": int, "first_date": str, "last_date": str} for the header
    examples:  example questions for the ask page
    """

    app = FastAPI(title="Research Insight Agent")

    if projects is None:
        projects = ProjectStore(Path(store.directory).parent / "ui_projects")

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
            client=client,
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
        return store.list(limit=max(1, min(limit, 500)))

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

    @app.get("/")
    def index():
        # Versioned asset links, so a browser never pairs a new page with an old
        # cached app.css or app.js after the code changes
        version = static_version()
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for name in ("app.css", "app.js"):
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
    """Changes whenever app.css or app.js changes on disk."""
    return str(int(max((STATIC_DIR / name).stat().st_mtime for name in ("app.css", "app.js"))))


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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Check the API key before the slow retriever startup
    llm = LLM(provider=args.provider, model=args.model, max_tokens=args.max_tokens,
              reasoning_effort=None if args.reasoning_effort == "none" else args.reasoning_effort)

    print("Loading the retriever and embedding model...")
    from src.rag.lance_retriever import LanceCombinedRetriever

    retriever = LanceCombinedRetriever(papers_path=args.papers, index_dir=args.index_dir)

    app = create_app(
        retriever,
        llm,
        BriefStore(args.briefs_dir),
        corpus=corpus_info(args.papers),
        examples=load_examples(args.benchmark),
        projects=ProjectStore(args.projects_dir),
    )

    import uvicorn

    print(f"Open http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
