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

I restarted the agent on port 8001 and fired 10 tagged agent requests from `evals/eval_set.jsonl` with metadata like `phase=langfuse_phase4`, `db_id=<db>`, and `source=phase4_smoke`. The local Langfuse API returned 11 traces total: 10 Phase 4 traces plus 1 smoke trace. Some requests exercised the revise loop, including the Formula 1 duplicate-row case and capped three-iteration failures.

## Phase 5

Per iteration pass rates:

| Metric | Value |
|---|---:|
| Total questions | 30 |
| Correct | 12 |
| Pass rate | 40.0% |
| Agent errors | 0 |
| Gold SQL errors | 0 |
| Latency p50 | 0.681s |
| Latency p95 | 2.869s |

| Iteration | Correct | Pass rate |
|---:|---:|---:|
| 0 | 10 / 30 | 33.3% |
| 1 | 11 / 30 | 36.7% |
| 2 | 12 / 30 | 40.0% |

So, agent shows some improvement


## Phase 6

Exp 1.

Saw: throughput of the model in output tokens is small (<1k output tokens/s), and some of issue/error fields are verbose

Hypo: Make error/issue less verbose, adjust prompt

Changed: Added enum values of the most popular issues/errors in input to make output shorted (enum value name is shorter than its description)

Result: Latency p95 droped significantly (16 -> 9 s)!


Exp 2.

Saw: compared load test with 1 rps and 10 rps: time to first token increased 20 -> 50 ms (1 rps -> 10 rps), the latency p95 increase (2s -> 9s)

Hypo: Queries interfere with each others.

Changed: increase parallelization of input prefill with --max-num-partial-prefills (1 -> 10)

Result: latency 9s -> 40s! It doesn't work


------------------------
wait a second, after rerun I cannot reproduce the 9s latency. I think env has changed.
Let's revaluate the baseline.
The issue is the caching of the load testing queries! In the production they will be unique.
So, I have to rerun vlllm model each time I run load test.
--max-num-partial-prefills missed -> p95 28.5s
--max-num-partial-prefills 1 (assumed default from docs) -> p95 32.4
--max-num-partial-prefills 1 (assumed default from docs, rerun) -> p95 35.9
--max-num-partial-prefills 2 -> p95 79.1

No, it doesn't work!

Exp 3.

The same Saw and hypo

Changed: MAX_MODEL_LEN (4096 -> 3072)

Result: latency p95 is 50.4s now

But I rerun with defalut params and got latency p95 = 59.6s. WTF???


----------------

Conclusion.

I'm out of time here.
The next step would require more detailed metrics.
Like p50, p95, p99 for input size, output size, how many shceduled iteration prefill took, how many chunks it produced, etc.

Now I don't see enough information to make next moves.
I looked at langfuse waterfall, looked at the timings of each query. I don't see the relation between longer queries. It looks like they generate more output tokens, but I should have aggregated metrics for it.

The Gant diagram should help as well.
