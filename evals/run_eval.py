"""Eval runner using execution accuracy.

Reads evals/eval_set.jsonl, calls the agent at AGENT_URL on each question,
then compares the agent's SQL output to the gold SQL by *executed rows*
(canonicalized: sorted, stringified, None-coerced to empty).

Run:
    uv run python evals/run_eval.py --out results/eval_baseline.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = ROOT / "evals" / "eval_set.jsonl"
DEFAULT_OUT_FILE = ROOT / "results" / "eval_baseline.json"
DB_DIR = ROOT / "data" / "bird"
AGENT_URL_DEFAULT = "http://localhost:8001/answer"


# ---------- Helpers (provided) -----------------------------------------

def run_sql(db_id: str, sql: str, timeout: float = 5.0) -> tuple[bool, list[tuple] | None, str | None]:
    """Run sql against db_id in read-only mode. Returns (ok, rows, error)."""
    path = DB_DIR / f"{db_id}.sqlite"
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout) as conn:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return True, rows, None
    except Exception as e:  # noqa: BLE001
        return False, None, f"{type(e).__name__}: {e}"


def canonicalize(rows: list[tuple] | None) -> list[tuple] | None:
    """Sort rows; coerce cells to str; None -> ''."""
    if rows is None:
        return None
    return sorted(tuple("" if c is None else str(c) for c in row) for row in rows)


def matches(gold_rows: list[tuple] | None, pred_rows: list[tuple] | None) -> bool:
    if gold_rows is None or pred_rows is None:
        return False
    return canonicalize(gold_rows) == canonicalize(pred_rows)


# ---------- Phase 5 implementation ------------------------------------

def _attempt_sqls(agent_response: dict[str, Any]) -> list[str]:
    """Extract generated/revised SQL attempts from the agent history."""
    attempts = [
        str(item.get("sql", "")).strip()
        for item in agent_response.get("history", [])
        if item.get("node") in {"generate_sql", "revise"} and item.get("sql")
    ]
    final_sql = str(agent_response.get("sql", "")).strip()
    if final_sql and (not attempts or attempts[-1] != final_sql):
        attempts.append(final_sql)
    return attempts


def eval_one(question: dict, agent_url: str) -> dict:
    """Score one question and capture correctness after each SQL attempt."""
    db_id = question["db_id"]
    gold_sql = question["gold_sql"]
    gold_ok, gold_rows, gold_error = run_sql(db_id, gold_sql)

    payload = {
        "question": question["question"],
        "db": db_id,
        "tags": {"phase": "eval", "db_id": db_id},
    }

    started = time.monotonic()
    agent_response: dict[str, Any] = {}
    agent_error: str | None = None
    status_code: int | None = None
    try:
        resp = httpx.post(agent_url, json=payload, timeout=120.0)
        status_code = resp.status_code
        resp.raise_for_status()
        agent_response = resp.json()
    except Exception as e:  # noqa: BLE001
        agent_error = f"{type(e).__name__}: {e}"

    attempts = _attempt_sqls(agent_response)
    per_iteration: dict[str, dict[str, Any]] = {}
    for idx, sql in enumerate(attempts):
        pred_ok, pred_rows, pred_error = run_sql(db_id, sql)
        correct = gold_ok and pred_ok and matches(gold_rows, pred_rows)
        per_iteration[str(idx)] = {
            "sql": sql,
            "correct": correct,
            "pred_ok": pred_ok,
            "pred_error": pred_error,
            "pred_row_count": len(pred_rows) if pred_rows is not None else None,
        }

    final_iteration = max((int(k) for k in per_iteration), default=-1)
    final_correct = per_iteration.get(str(final_iteration), {}).get("correct", False)

    return {
        "question": question["question"],
        "db_id": db_id,
        "gold_sql": gold_sql,
        "gold_ok": gold_ok,
        "gold_error": gold_error,
        "gold_row_count": len(gold_rows) if gold_rows is not None else None,
        "agent_status_code": status_code,
        "agent_error": agent_error,
        "agent_iterations": agent_response.get("iterations"),
        "agent_ok": agent_response.get("ok"),
        "final_sql": agent_response.get("sql", ""),
        "final_correct": bool(final_correct),
        "final_iteration": final_iteration,
        "latency_seconds": time.monotonic() - started,
        "per_iteration": per_iteration,
    }


def summarize(results: list[dict]) -> dict:
    """Aggregate overall and carry-forward per-iteration pass rates."""
    total = len(results)
    if total == 0:
        return {
            "total": 0,
            "correct": 0,
            "pass_rate": 0.0,
            "per_iteration": {},
            "agent_errors": 0,
            "gold_errors": 0,
        }

    max_iter = max(
        (int(k) for r in results for k in r.get("per_iteration", {}).keys()),
        default=0,
    )

    per_iteration: dict[str, dict[str, float | int]] = {}
    for idx in range(max_iter + 1):
        correct_at_idx = 0
        for r in results:
            last_correct = False
            for j in range(idx + 1):
                entry = r.get("per_iteration", {}).get(str(j))
                if entry is not None:
                    last_correct = bool(entry.get("correct", False))
            if last_correct:
                correct_at_idx += 1
        per_iteration[str(idx)] = {
            "correct": correct_at_idx,
            "pass_rate": correct_at_idx / total,
        }

    final_correct = sum(1 for r in results if r.get("final_correct"))
    latencies = sorted(float(r.get("latency_seconds", 0.0)) for r in results)

    def pct(p: float) -> float:
        if not latencies:
            return 0.0
        k = round(p * (len(latencies) - 1))
        return latencies[int(k)]

    return {
        "total": total,
        "correct": final_correct,
        "pass_rate": final_correct / total,
        "per_iteration": per_iteration,
        "agent_errors": sum(1 for r in results if r.get("agent_error")),
        "gold_errors": sum(1 for r in results if not r.get("gold_ok")),
        "latency_p50_seconds": pct(0.50),
        "latency_p95_seconds": pct(0.95),
    }


# ---------- Main (provided) --------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-set", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_FILE)
    parser.add_argument("--agent-url", default=AGENT_URL_DEFAULT)
    args = parser.parse_args()

    questions = [json.loads(line) for line in args.eval_set.read_text().splitlines() if line.strip()]
    print(f"Loaded {len(questions)} eval questions from {args.eval_set}")

    results: list[dict] = []
    t0 = time.monotonic()
    for i, q in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q['db_id']}: {q['question'][:60]}...", flush=True)
        results.append(eval_one(q, args.agent_url))
    elapsed = time.monotonic() - t0

    summary = summarize(results)
    out = {
        "summary": summary,
        "wall_clock_seconds": elapsed,
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2))
    print(f"Wrote {args.out}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
