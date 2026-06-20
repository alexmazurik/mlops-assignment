#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
MODEL="${MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507}"

cd "$(dirname "$0")/.."

payload="$(jq -n \
  --arg model "$MODEL" \
  '{
    model: $model,
    messages: [
      {
        role: "system",
        content: "You are a text-to-SQL assistant. Given a database id and a natural language question, output only the SQL query."
      },
      {
        role: "user",
        content: "Database id: formula_1\nQuestion: What is the coordinates location of the circuits for Australian grand prix?"
      }
    ],
    temperature: 0,
    max_tokens: 512
  }')"

printf 'Curl command:\n'
printf 'curl -sS %q -H %q -d %q\n\n' \
  "$BASE_URL/v1/chat/completions" \
  "Content-Type: application/json" \
  "$payload"

curl -sS "$BASE_URL/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$payload" |
  jq -r '.choices[0].message.content'
