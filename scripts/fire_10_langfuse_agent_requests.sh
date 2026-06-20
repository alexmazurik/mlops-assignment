#!/usr/bin/env bash
set -euo pipefail

AGENT_URL="${AGENT_URL:-http://localhost:8001/answer}"
EVAL_SET="${EVAL_SET:-evals/eval_set.jsonl}"
PHASE="${PHASE:-langfuse_phase4}"
SOURCE="${SOURCE:-phase4_smoke}"
COUNT="${COUNT:-10}"

python3 - "$AGENT_URL" "$EVAL_SET" "$PHASE" "$SOURCE" "$COUNT" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

agent_url, eval_set, phase, source, count_text = sys.argv[1:6]
count = int(count_text)

items = []
for line in Path(eval_set).read_text().splitlines():
    if not line.strip():
        continue
    items.append(json.loads(line))
    if len(items) >= count:
        break

for i, item in enumerate(items, 1):
    db_id = item["db_id"]
    payload = {
        "question": item["question"],
        "db": db_id,
        "tags": {
            "phase": phase,
            "db_id": db_id,
            "source": source,
        },
    }
    request = urllib.request.Request(
        agent_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        body = json.loads(response.read())

    print(json.dumps({
        "i": i,
        "db": db_id,
        "ok": body.get("ok"),
        "iterations": body.get("iterations"),
        "history": [step.get("node") for step in body.get("history", [])],
    }))
PY
