"""LangGraph agent: text-to-SQL with verify+revise loop.

Graph shape:

    START -> attach_schema -> generate_sql -> execute -> verify
                                                          |
                                              ok=true ----+----> END
                                                          |
                                              ok=false ---+----> revise -> execute -> verify (loop)

Loop is capped at MAX_ITERATIONS total generate/revise calls.
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from agent import prompts
from agent.execution import ExecutionResult, execute_sql
from agent.schema import render_schema

# Total generate + revise calls before the loop is forced to stop.
MAX_ITERATIONS = 3

VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000/v1")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3-30B-A3B-Instruct-2507")
# vLLM ignores the key, but a hosted OpenAI-compatible provider needs a real one.
LLM_API_KEY = os.environ.get("OPENAI_API_KEY", "not-needed")


@dataclass
class AgentState:
    """State threaded through the graph."""

    question: str
    db_id: str
    schema: str = ""
    sql: str = ""
    execution: ExecutionResult | None = None
    verify_ok: bool = False
    verify_issue: str = ""
    iteration: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)


def llm(max_tokens: int = 256) -> ChatOpenAI:
    """Chat client pointed at VLLM_BASE_URL (your local vLLM by default)."""
    return ChatOpenAI(
        model=VLLM_MODEL,
        base_url=VLLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0.0,
        max_tokens=max_tokens,
    )


# ---- Output parsing helpers ------------------------------------------

def _message_text(content: Any) -> str:
    """Normalize LangChain message content into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


def _extract_sql(text: str) -> str:
    """Pull a SQL statement out of an LLM reply, stripping fences/prose."""
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidate = (fenced.group(1) if fenced else text).strip()

    statement = re.search(r"(?is)\b(with|select)\b.*?;", candidate)
    if statement is None:
        statement = re.search(r"(?is)\b(with|select)\b.*", candidate)
    if statement is not None:
        candidate = statement.group(0)

    return candidate.strip().strip("`").strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Find and parse the first JSON object in a model response."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        candidate = candidate.strip()
        for idx, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                obj, _end = decoder.raw_decode(candidate[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def _execution_is_vacuous(execution: ExecutionResult | None) -> bool:
    """Detect successful-but-useless result sets that should be revised."""
    if execution is None or not execution.ok:
        return False
    if execution.row_count == 0:
        return True
    rows = execution.rows or []
    return bool(rows) and all(all(cell is None for cell in row) for row in rows)


def _execution_has_duplicate_rows(execution: ExecutionResult | None) -> bool:
    """Detect duplicate result rows from accidental fan-out joins."""
    if execution is None or not execution.ok or not execution.rows:
        return False
    rows = execution.rows
    return len(rows) > 1 and len(set(rows)) < len(rows)


def _parse_verify_response(text: str, execution: ExecutionResult | None) -> tuple[bool, str]:
    """Parse verifier JSON with execution-based fallbacks."""
    obj = _extract_json_object(text)
    if obj is not None:
        ok = obj.get("ok", False)
        if isinstance(ok, str):
            ok = ok.strip().lower() in {"true", "yes", "1", "ok"}
        issue = str(obj.get("issue", "")).strip()
        return bool(ok), issue if issue else ("" if ok else "Verifier rejected the SQL.")

    lowered = text.lower()
    if '"ok": true' in lowered or "ok: true" in lowered:
        return True, ""
    if '"ok": false' in lowered or "ok: false" in lowered:
        return False, text.strip()[:500] or "Verifier rejected the SQL."

    if execution is None:
        return False, "No SQL execution result was available."
    if not execution.ok:
        return False, execution.error or "SQL execution failed."
    if execution.row_count == 0:
        return False, "Query returned zero rows; revise unless the question explicitly expects no matches."
    return False, "Verifier did not return parseable JSON."


# ---- Nodes ------------------------------------------------------------

def _attach_schema(state: AgentState) -> dict:
    """Provided. Render the DB schema once at the start of the run."""
    schema = render_schema(state.db_id)
    prefix = schema[:100]
    suffix = schema[-100:] if len(schema) > 100 else schema
    print(
        f"schema chars={len(schema)} "
        f"prefix={prefix!r} "
        f"suffix={suffix!r}",
        file=sys.stderr,
    )
    return {"schema": schema}


def generate_sql_node(state: AgentState) -> dict:
    """Generate the first SQL candidate."""
    response = llm(max_tokens=256).invoke([
        ("system", prompts.GENERATE_SQL_SYSTEM),
        ("user", prompts.GENERATE_SQL_USER.format(
            schema=state.schema,
            question=state.question,
        )),
    ])
    sql = _extract_sql(_message_text(response.content))
    return {
        "sql": sql,
        "iteration": state.iteration + 1,
        "history": state.history + [{"node": "generate_sql", "sql": sql}],
    }


def execute_node(state: AgentState) -> dict:
    """Provided. Runs the SQL and stores the result."""
    return {"execution": execute_sql(state.db_id, state.sql)}


def verify_node(state: AgentState) -> dict:
    """Decide whether state.execution plausibly answers state.question."""
    execution_text = state.execution.render() if state.execution is not None else "ERROR: no execution result"
    response = llm(max_tokens=96).invoke([
        ("system", prompts.VERIFY_SYSTEM),
        ("user", prompts.VERIFY_USER.format(
            schema=state.schema,
            question=state.question,
            sql=state.sql,
            execution=execution_text,
        )),
    ])
    ok, issue = _parse_verify_response(_message_text(response.content), state.execution)
    if ok and _execution_is_vacuous(state.execution):
        ok = False
        issue = "SQL executed but returned no usable values; revise the filters, joins, or selected column."
    elif ok and _execution_has_duplicate_rows(state.execution):
        ok = False
        issue = "Result contains duplicate rows; revise with DISTINCT or fix the join fan-out."
    return {
        "verify_ok": ok,
        "verify_issue": issue,
        "history": state.history + [{
            "node": "verify",
            "ok": ok,
            "issue": issue,
            "iteration": state.iteration,
        }],
    }


def revise_node(state: AgentState) -> dict:
    """Produce a revised SQL query from the verifier complaint."""
    execution_text = state.execution.render() if state.execution is not None else "ERROR: no execution result"
    response = llm(max_tokens=256).invoke([
        ("system", prompts.REVISE_SYSTEM),
        ("user", prompts.REVISE_USER.format(
            schema=state.schema,
            question=state.question,
            sql=state.sql,
            execution=execution_text,
            issue=state.verify_issue or "The verifier rejected the SQL.",
        )),
    ])
    sql = _extract_sql(_message_text(response.content))
    return {
        "sql": sql,
        "iteration": state.iteration + 1,
        "verify_ok": False,
        "verify_issue": "",
        "history": state.history + [{"node": "revise", "sql": sql}],
    }


def route_after_verify(state: AgentState) -> str:
    """Route to END on success/cap, otherwise revise and re-execute."""
    if state.verify_ok or state.iteration >= MAX_ITERATIONS:
        return "end"
    return "revise"


# ---- Graph wiring -----------------------------------------------------

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("attach_schema", _attach_schema)
    g.add_node("generate_sql", generate_sql_node)
    g.add_node("execute", execute_node)
    g.add_node("verify", verify_node)
    g.add_node("revise", revise_node)

    g.add_edge(START, "attach_schema")
    g.add_edge("attach_schema", "generate_sql")
    g.add_edge("generate_sql", "execute")
    g.add_edge("execute", "verify")
    g.add_conditional_edges(
        "verify",
        route_after_verify,
        {"revise": "revise", "end": END},
    )
    g.add_edge("revise", "execute")
    return g.compile()


graph = build_graph()
