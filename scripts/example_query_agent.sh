#!/usr/bin/env bash
set -euo pipefail

curl -X POST http://localhost:8001/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "List down Ajax'"'"'s superpowers.", "db": "superhero"}' | jq
