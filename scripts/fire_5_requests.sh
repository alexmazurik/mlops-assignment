#!/usr/bin/env bash
set -euo pipefail

URL="${VLLM_URL:-http://localhost:8000/v1/chat/completions}"
MODEL="${VLLM_MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507}"

prompts=(
  "Return only a SQLite SELECT query. Question: List down Ajax's superpowers."
  "Return only a SQLite SELECT query. Question: How many superheroes have the super power of Super Strength?"
  "Return only a SQLite SELECT query. Question: What is the coordinates location of the circuits for Australian grand prix?"
  "Return only a SQLite SELECT query. Question: How many male clients in 'Hl.m. Praha' district?"
  "Return only a SQLite SELECT query. Question: What is the type of the card Ancestor's Chosen as originally printed?"
)

for i in "${!prompts[@]}"; do
  request_number=$((i + 1))
  echo "== vLLM request ${request_number}/5 =="

  python3 - "$URL" "$MODEL" "${prompts[$i]}" <<'PY'
import json
import sys
import urllib.request

url, model, prompt = sys.argv[1:4]
payload = {
    "model": model,
    "messages": [
        {"role": "system", "content": "You are a text-to-SQL assistant. Return only SQL."},
        {"role": "user", "content": prompt},
    ],
    "temperature": 0,
    "max_tokens": 160,
}
request = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json", "Authorization": "Bearer not-needed"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=120) as response:
    print(response.read().decode("utf-8"))
PY

  if (( i < 4 )); then
    sleep_seconds=$((i + 1))
    echo "Sleeping ${sleep_seconds}s..."
    sleep "$sleep_seconds"
  fi
done
