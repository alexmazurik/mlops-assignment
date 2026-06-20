"""FastAPI wrapper exposing the agent over HTTP.

Run:
    uv run uvicorn agent.server:app --host 0.0.0.0 --port 8001

The /answer endpoint accepts {question, db, tags?} and returns the
agent's final SQL, the result rows, and per-iteration history.
"""
from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

load_dotenv()

from agent.graph import AgentState, graph  # noqa: E402

# Langfuse is required for this assignment phase. Fail at startup instead of
# silently running without traces.
_missing_langfuse = [
    name for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")
    if not os.environ.get(name)
]
if _missing_langfuse:
    raise RuntimeError(f"Missing Langfuse environment variables: {', '.join(_missing_langfuse)}")

from langfuse.langchain import CallbackHandler

_lf_handler: Any = CallbackHandler()


app = FastAPI()


class AnswerRequest(BaseModel):
    question: str
    db: str
    tags: dict[str, str] = {}


class AnswerResponse(BaseModel):
    sql: str
    rows: list[list[Any]] | None
    iterations: int
    ok: bool
    error: str | None = None
    history: list[dict[str, Any]] = []


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/answer", response_model=AnswerResponse)
def answer(req: AnswerRequest) -> AnswerResponse:
    state = AgentState(question=req.question, db_id=req.db)
    trace_tags = [f"{key}:{value}" for key, value in req.tags.items()]
    config: dict[str, Any] = {
        "callbacks": [_lf_handler],
        "metadata": req.tags,
        "tags": trace_tags,
    }
    try:
        final = graph.invoke(state, config=config)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    sql = final.get("sql", "")
    iteration = final.get("iteration", 0)
    history = final.get("history", [])
    execution = final.get("execution")

    if execution is None:
        return AnswerResponse(
            sql=sql,
            rows=None,
            iterations=iteration,
            ok=False,
            error="agent produced no execution result",
            history=history,
        )
    if not execution.ok:
        return AnswerResponse(
            sql=sql,
            rows=None,
            iterations=iteration,
            ok=False,
            error=execution.error,
            history=history,
        )

    rows = [list(r) for r in (execution.rows or [])]
    if not final.get("verify_ok", False):
        return AnswerResponse(
            sql=sql,
            rows=rows,
            iterations=iteration,
            ok=False,
            error=final.get("verify_issue") or "verifier rejected final SQL",
            history=history,
        )

    return AnswerResponse(
        sql=sql,
        rows=rows,
        iterations=iteration,
        ok=True,
        history=history,
    )
