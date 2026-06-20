#!/usr/bin/env bash
set -euo pipefail

URL="${AGENT_URL:-http://localhost:8001/answer}"

questions=(
  '{"question": "List down Ajax'"'"'s superpowers.", "db": "superhero"}'
  '{"question": "How many superheroes have the super power of \"Super Strength\"?", "db": "superhero"}'
  '{"question": "What is the coordinates location of the circuits for Australian grand prix?", "db": "formula_1"}'
  '{"question": "How many male clients in '\''Hl.m. Praha'\'' district?", "db": "financial"}'
  '{"question": "What is the type of the card \"Ancestor'"'"'s Chosen\" as originally printed?", "db": "card_games"}'
)

for i in "${!questions[@]}"; do
  n=$((i + 1))
  echo "== Request ${n}/5 =="
  curl -sS -X POST "$URL" \
    -H "Content-Type: application/json" \
    -d "${questions[$i]}" | jq
  echo

  if (( i < 4 )); then
    sleep_for=$((i + 1))
    echo "Sleeping ${sleep_for}s..."
    sleep "$sleep_for"
  fi
done
