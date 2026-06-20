# MLOps Assignment Report

## Serving Configuration

Model: `Qwen/Qwen3-30B-A3B-Instruct-2507` on one H100 80GB, served by vLLM's OpenAI-compatible API at `http://localhost:8000/v1`.

The launch script is `scripts/start_vllm.sh`.

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

## Agent And Eval Results

The agent is a LangGraph loop:

`attach_schema -> generate_sql -> execute -> verify -> (revise -> execute -> verify)*`

It stops when verification succeeds or after 3 total generate/revise attempts. The verifier checks SQL execution errors, ignored filters/order/limits, empty results, all-NULL aggregate outputs, and duplicate rows from join fan-out. A targeted Formula 1 eval case initially returned duplicate circuit coordinates; the verifier forced a revision and the revised SQL added `DISTINCT`.

| Run | Correct | Pass rate | Iter 0 | Iter 1 | Iter 2 | Agent errors |
|---|---:|---:|---:|---:|---:|---:|
| `results/eval_baseline.json` | 12 / 30 | 40.0% | 33.3% | 36.7% | 40.0% | 0 |
| `results/eval_after_tuning.json` | 12 / 30 | 40.0% | 33.3% | 36.7% | 40.0% | 0 |

The loop is doing real, but modest, work: it improves execution accuracy by 2 questions over first-draft SQL. The deterministic guards also prevent false confidence. For one financial question, the agent returned `ok=false` after the cap instead of presenting an all-NULL aggregate as a valid answer.

Langfuse callback wiring is present in `agent/server.py`, and the eval/load drivers pass metadata tags into graph invocation. Traces were not captured in this run because `.env` did not contain local Langfuse public/secret keys.

## Observability Dashboard

`infra/grafana/provisioning/dashboards/serving.json` contains 10 panels covering latency, throughput, scheduler state, and KV cache health.

| Category | Panels |
|---|---|
| Latency | E2E p50/p95/p99, lifecycle breakdown, time per output token |
| Throughput | request throughput, prompt/generation token throughput, per-request token shape |
| Scheduler | running/waiting requests |
| KV cache | KV usage, preemptions, prefix-cache hit rate |

The dashboard uses vLLM metrics including `vllm:e2e_request_latency_seconds_bucket`, `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:kv_cache_usage_perc`, `vllm:prompt_tokens_total`, `vllm:generation_tokens_total`, `vllm:prefix_cache_hits_total`, and `vllm:prefix_cache_queries_total`.

The VM did not have a usable headless browser or Grafana image renderer package, so the PNG files under `screenshots/` are generated evidence images from the local APIs, dashboard JSON, and saved result files; the Langfuse PNGs are explicit placeholders because no keys were configured.

## SLO Work

Target SLO: p95 end-to-end agent latency under 5 seconds at 10+ full agent runs per second for 5 minutes.

| Run | Window | OK | HTTP 500 | Timeout/client errors | Achieved RPS | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| First 10 RPS probe | 60s | 520 / 600 | 79 | 1 | 5.00 | 17.1s | 29.0s | 38.3s |
| After verifier prompt trim | 60s | 521 / 600 | 78 | 1 | 5.00 | 12.2s | 22.3s | 32.0s |
| After schema FK fix | 60s | 598 / 600 | 0 | 2 | 5.00 | 26.2s | 40.5s | 45.9s |
| Final 10 RPS run | 300s | 1070 / 3000 | 0 | 1930 | 8.33 | 63.0s | 112.9s | 119.3s |

Iteration log:

| Saw | Hypothesized | Changed | Result |
|---|---|---|---|
| 10 RPS p95 was 29s and 79 requests returned HTTP 500. vLLM queue stayed at 0, peak running requests was 38, peak KV use was about 14%, and vLLM p95 was about 4.47s. | H100/KV cache was not saturated; agent prompt size and a server bug were dominating end-to-end behavior. | Capped generation tokens for SQL/revise/verify and removed the full schema from the verifier prompt. | p95 improved from 29.0s to 22.3s, but HTTP 500s persisted. |
| 500 bodies were `AttributeError: 'NoneType' object has no attribute 'replace'`. | Some SQLite foreign keys have a NULL target column and the schema renderer tried to quote `None`. | Rendered `REFERENCES "table"` when `PRAGMA foreign_key_list` target column is NULL. | HTTP 500s dropped to 0 on the next 10 RPS probe. |
| Post-fix 10 RPS p95 rose to 40.5s even though HTTP 500s disappeared. Prometheus still showed no vLLM waiting queue and only about 13% KV usage, with vLLM p95 around 4.3s. | Previously crashing requests were now doing full multi-call agent work; the bottleneck is dependent LLM calls per agent run, not KV cache. | Kept the correctness-preserving verifier loop and measured the real 5-minute SLO instead of weakening the agent. | Final run missed the SLO: p95 112.9s, achieved 8.33 RPS, and many requests timed out. |

Verdict: the SLO was missed. The serving layer did not show KV pressure or scheduler backlog during the 60-second diagnosis probe, but each product-level request requires roughly 2-3 dependent model calls. At 10 full agent runs per second, those dependent calls create a large slow tail even when individual vLLM calls are only a few seconds at p95.

## What I Would Do Next

First, make verification cheaper: run deterministic SQL/result guards before the LLM verifier and skip the verifier call for simple successful SELECTs that pass schema/filter heuristics. Second, add schema linking or table retrieval so generation prompts include only relevant tables. Third, separate traffic classes so first-draft generation gets latency priority while revise calls use lower priority and tighter token budgets. Fourth, sweep vLLM scheduler settings with the real prompt distribution, especially `--kv-cache-memory`, `--max-num-batched-tokens`, and priority scheduling, while tracking both vLLM p95 and end-to-end agent p95. Finally, capture Langfuse traces with local keys enabled so slow requests can be broken down by `generate_sql`, `verify`, and `revise` spans instead of inferred from aggregate metrics.
