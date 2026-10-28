#!/bin/sh
set -eu

exec vllm serve "${NEMOTRON_MODEL:-nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16}" \
  --host "${NEMOTRON_HOST:-127.0.0.1}" \
  --port "${NEMOTRON_PORT:-8000}" \
  --served-model-name nemotron-local \
  --dtype bfloat16 \
  --max-model-len 4096 \
  --max-num-seqs 2 \
  --max-num-batched-tokens 512 \
  --gpu-memory-utilization 0.5 \
  --mamba-ssm-cache-dtype float32 \
  --no-enable-prefix-caching \
  --generation-config vllm