#!/usr/bin/env bash
#
# Start vLLM with the assignment serving configuration.
# Tunables are environment-overridable so Phase 6 sweeps can change one
# variable at a time without editing the script.

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen3-30B-A3B-Instruct-2507}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-4096}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-64}"
MAX_NUM_BATCHED_TOKENS="${MAX_NUM_BATCHED_TOKENS:-12288}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.92}"

exec uv run python -m vllm.entrypoints.openai.api_server     \
    --model "$MODEL"     \
    --served-model-name "$MODEL"     \
    --host "$HOST"     \
    --port "$PORT"     \
    --dtype bfloat16     \
    --max-model-len "$MAX_MODEL_LEN"     \
    --max-num-seqs "$MAX_NUM_SEQS"     \
    --max-num-batched-tokens "$MAX_NUM_BATCHED_TOKENS"     \
    --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION"     \
    --enable-prefix-caching     \
    --enable-chunked-prefill     \
    --disable-log-requests
