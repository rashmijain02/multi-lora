#!/bin/sh
set -eu

if [ "$#" -lt 2 ]; then
  printf '%s\n' 'Usage: sh scripts/train-nemotron.sh DATASET_DIR NEW_ADAPTER_DIR [MLX-LM options]' >&2
  printf '%s\n' 'Relative paths are resolved from the workshop root.' >&2
  exit 2
fi

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
workshop_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
cd "$workshop_dir"
dataset_dir=$1
adapter_dir=$2
shift 2
for split in train valid; do
  if [ ! -s "$dataset_dir/$split.jsonl" ]; then
    printf 'Missing or empty dataset split: %s/%s.jsonl\n' "$dataset_dir" "$split" >&2
    exit 2
  fi
done
if [ -e "$adapter_dir" ]; then
  printf 'Adapter directory already exists; choose a new run: %s\n' "$adapter_dir" >&2
  exit 2
fi

if [ -n "${MLX_PYTHON:-}" ]; then
  python_bin=$MLX_PYTHON
else
  python_bin=$(brew --prefix vllm-metal)/libexec/bin/python
fi
if [ ! -x "$python_bin" ]; then
  printf '%s\n' 'MLX Python is unavailable; install vLLM-Metal or set MLX_PYTHON.' >&2
  exit 2
fi
printf '%s\n' 'Stop the inference server first to leave memory available for training.' >&2
exec "$python_bin" -m mlx_lm lora \
  --config config/nemotron_mlx_lora.yaml \
  --train \
  --data "$dataset_dir" \
  --adapter-path "$adapter_dir" \
  "$@"