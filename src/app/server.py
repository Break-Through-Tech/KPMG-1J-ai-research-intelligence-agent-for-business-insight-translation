# Web UI for consultants: ask a question, get a cited business brief.
#
# python -m src.app                      (Groq, needs GROQ_API_KEY)
# python -m src.app --provider gemini    (needs GEMINI_API_KEY)
# then open http://localhost:8000
#
# LLM calls per action: ask = 2, rewrite for another audience = 1,
# everything else (open, approve, request changes, copy link) = 0.

import argparse
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.pipeline.pipeline import answer_query, translate_summary
from src.translation.prompts import AUDIENCES, DEFAULT_AUDIENCE

from .checks import run_checks
from .store import BriefStore

STATIC_DIR = Path(__file__).parent / "static"

STATUSES = {"draft", "approved", "changes"}

# More papers make the summary prompt longer and slower without better briefs
MAX_PAPERS = 5

# Benchmark questions offered as one-click examples on the ask page
EXAMPLE_QUERY_IDS = ["Q11", "Q13", "Q12", "Q19"]


class AskRequest(BaseModel):
    question: str
    audience: str = DEFAULT_AUDIENCE
    top_k: int = 5


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


def create_app(retriever, llm, store, corpus=None, examples=None):
    """
    retriever: anything with search(query, top_k) (see src/pipeline/pipeline.py)
    llm:       anything with generate(system_prompt, user_prompt)
    store:     a BriefStore
    corpus:    {"papers": int, "first_date": str, "last_date": str} for the header
    examples:  example questions for the ask page
    """

    app = FastAPI(title="Research Insight Agent")

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

        result = run_llm(lambda: answer_query(
            question, retriever, llm, top_k=request.top_k,
            translate=True, audience=request.audience,
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
            **result,
            "briefs": {},
        }

        if insight:
            record["briefs"][request.audience] = brief_entry(result, insight)

        return store.save(record)

    @app.get("/api/briefs")
    def list_briefs():
        return store.list()

    @app.get("/api/briefs/{brief_id}")
    def get_brief(brief_id: str):
        return load(brief_id)

    @app.post("/api/briefs/{brief_id}/status")
    def set_status(brief_id: str, request: StatusRequest):
        if request.status not in STATUSES:
            raise HTTPException(400, f"Unknown status {request.status!r}")

        record = load(brief_id)
        record["status"] = request.status
        record["note"] = request.note.strip()
        record["reviewed_at"] = now()
        return store.save(record)

    @app.post("/api/briefs/{brief_id}/rewrite")
    def rewrite(brief_id: str, request: RewriteRequest):
        check_audience(request.audience)
        record = load(brief_id)

        if not record["sources"]:
            raise HTTPException(400, "No research was found for this question, so there is nothing to rewrite.")

        # Reuses the saved summary, so this is one LLM call, not two
        insight = run_llm(lambda: translate_summary(
            record["query"], record["summary"], record["sources"], llm, request.audience,
        ))

        record["briefs"][request.audience] = brief_entry(record, insight)
        record["audience"] = request.audience
        record["status"] = "draft"
        record["note"] = ""
        return store.save(record)

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


def corpus_info(papers_path):
    import pandas as pd

    dates = pd.read_parquet(papers_path, columns=["published_date"])["published_date"]
    dates = pd.to_datetime(dates)

    return {
        "papers": int(len(dates)),
        "first_date": dates.min().date().isoformat(),
        "last_date": dates.max().date().isoformat(),
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
    parser.add_argument("--papers", default="data/release/papers_clean.parquet")
    parser.add_argument("--index-dir", default="data/index")
    parser.add_argument("--benchmark", default="evaluation/benchmark_queries.csv")
    parser.add_argument("--briefs-dir", default="data/ui_briefs")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # Check the API key before the slow retriever startup
    llm = LLM(provider=args.provider, model=args.model, max_tokens=args.max_tokens)

    print("Loading the retriever and embedding model...")
    from src.rag.lance_retriever import LanceCombinedRetriever

    retriever = LanceCombinedRetriever(papers_path=args.papers, index_dir=args.index_dir)

    app = create_app(
        retriever,
        llm,
        BriefStore(args.briefs_dir),
        corpus=corpus_info(args.papers),
        examples=load_examples(args.benchmark),
    )

    import uvicorn

    print(f"Open http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
