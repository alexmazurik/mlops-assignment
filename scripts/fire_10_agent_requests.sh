#!/usr/bin/env bash
set -euo pipefail

URL="${AGENT_URL:-http://localhost:8001/answer}"

questions=(
  "{\"question\": \"List down Ajax's superpowers.\", \"db\": \"superhero\"}"
  "{\"question\": \"How many superheroes have the super power of \\\"Super Strength\\\"?\", \"db\": \"superhero\"}"
  "{\"question\": \"What is the coordinates location of the circuits for Australian grand prix?\", \"db\": \"formula_1\"}"
  "{\"question\": \"How many male clients in 'Hl.m. Praha' district?\", \"db\": \"financial\"}"
  "{\"question\": \"What is the type of the card \\\"Ancestor's Chosen\\\" as originally printed?\", \"db\": \"card_games\"}"
  "{\"question\": \"List the top five schools, by descending order, from the highest to the lowest, the most number of Enrollment (Ages 5-17). Please give their NCES school identification number.\", \"db\": \"california_schools\"}"
  "{\"question\": \"What is the average number of crimes committed in 1995 in regions where the number exceeds 4000 and the region has accounts that are opened starting from the year 1997?\", \"db\": \"financial\"}"
  "{\"question\": \"What is the average fastest lap time in seconds for Lewis Hamilton in all the Formula_1 races?\", \"db\": \"formula_1\"}"
  "{\"question\": \"From race no. 50 to 100, how many finishers have been disqualified?\", \"db\": \"formula_1\"}"
  "{\"question\": \"Calculate the difference of the total amount spent in all events by the Student_Club in year 2019 and 2020.\", \"db\": \"student_club\"}"
)

total_requests="${#questions[@]}"

for i in "${!questions[@]}"; do
  n=$((i + 1))
  echo "== Request ${n}/${total_requests} =="
  curl -sS -X POST "$URL" \
    -H "Content-Type: application/json" \
    -d "${questions[$i]}" | jq
  echo

  if (( i < total_requests - 1 )); then
    sleep_for=$((i + 1))
    echo "Sleeping ${sleep_for}s..."
    sleep "$sleep_for"
  fi
done
