# MLOps Assignment Report


Model: `Qwen/Qwen3-30B-A3B-Instruct-2507` on one H100 80GB, served by vLLM's OpenAI-compatible API at `http://localhost:8000/v1`.

The launch script is `scripts/start_vllm.sh`.

## Phase 1

| Setting | Value | Why |
|---|---:|---|
| `--dtype` | `bfloat16` | Native H100 format; keeps memory use practical without forcing fp16 conversion. |
| `--max-model-len` | `4096` | Covers the observed schema-heavy text-to-SQL prompts without paying for unnecessary long-context KV capacity. |
| `--max-num-seqs` | `64` | Allows concurrent short generations while avoiding an overly large batch that hurts tail latency. |
| `--max-num-batched-tokens` | `12288` | Gives prefill room for 1.5-3K token prompts while leaving decode responsive. |
| `--gpu-memory-utilization` | `0.92` | Uses most of the H100 while leaving runtime headroom. |
| `--enable-prefix-caching` | on | Reuses repeated system/schema-prefix tokens across eval and load traffic. |
| `--enable-chunked-prefill` | on | Prevents large schema prompts from monopolizing the scheduler. |
| `--disable-log-requests` | on | Avoids per-request logging overhead during load tests. |

Two setup issues had to be fixed before serving was stable: `transformers` was pinned to `<5` because vLLM 0.10.2 was incompatible with the previously resolved tokenizer path, and `python3-dev` headers were installed because vLLM's torch compile path needed `Python.h`.

Manual smoke checks on eval questions returned sensible SQL for Formula 1 circuit coordinates, Ajax superhero powers, and top California schools by enrollment.

I fired the query from scripts/example_query_hardcoded.sh on the screenshots/vllm_manual_query.png

## Phase 2

I fired 5 seconds with 1, 2, 3 and 4 seconds between them from scripts/fire_5_requests.sh

## Phase 3

I run , at least one query finished with 2 iterations, revised the issue

`issue": "Result contains duplicate rows; revise with DISTINCT or fix the join fan-out.",`

which looks reasonable

## Phase 4

Langfuse is now integrated. `.env` contains `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`; `agent/server.py` maps `LANGFUSE_BASE_URL` to `LANGFUSE_HOST` so the installed Langfuse client can pick it up.

I restarted the agent on port 8001 and fired 10 tagged agent requests from `evals/eval_set.jsonl` with metadata like `phase=langfuse_phase4`, `db_id=<db>`, and `source=phase4_smoke`. The local Langfuse API returned 11 traces total: 10 Phase 4 traces plus 1 smoke trace. Some requests exercised the revise loop, including the Formula 1 duplicate-row case and capped three-iteration failures.

Evidence files: `screenshots/langfuse_trace.png` and `screenshots/langfuse_tags.png`. They are generated from the local Langfuse API because this VM still does not have a usable browser screenshot tool.
