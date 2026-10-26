# Apple Silicon Nemotron LoRA Lab

## Goal And Scope

Fine-tune a Nemotron email adapter locally with MLX-LM, evaluate it, and only
then consider serving it. **LoRA training is the primary goal; vLLM is an
optional inference service, not a trainer.**

This is an optional Mac lab alongside the existing classification and persona
notebooks, not a replacement for their pinned Qwen/Transformers/PEFT pipeline.
It uses `nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16`, a hybrid Mamba/attention model.
That is a different base and prompt contract from the optional Llama Nemotron
Nano 8B profile in [the NVIDIA findings](NEMOTRON_LORA_FINDINGS.md).
Do not reuse adapters across those models or claim this lab integrates with
the existing router, persona registry, or evaluation pipeline automatically.

Prerequisites: Apple Silicon, macOS 15 or later, Homebrew, a trusted dataset,
and enough free memory and disk. Initial verification used an M5 Pro with
48 GB unified memory; this is not a measured training-memory minimum.
The 4B BF16 checkpoint is approximately 8 GB before runtime overhead.

## Workshop Plan

Allow 90-120 minutes plus downloads, training, and evaluation time. Full training
duration and quality are not promised.

| Lab | Participant activity | Exit evidence |
| --- | --- | --- |
| 1. Environment | Keep MLX separate from the existing PEFT environment | Metal and version checks |
| 2. Base identity | Select and record the model revision and prompt contract | Reviewed base identity |
| 3. LoRA mechanics | Run a tiny random-model gradient check | Finite nonzero gradients and Adam step |
| 4. Email data | Prepare private train/validation splits | Audited JSONL and split lineage |
| 5. Train | Run a bounded smoke, then a separate longer experiment | Independent adapter directories |
| 6. Evaluate | Compare base and adapted responses on the same held-out inputs | Paired quality and failure review |
| 7. Multiple adapters | Repeat with another domain/client against the same base | Separate, compatible adapter runs |
| 8. Serve | Test local API and optional trusted-LAN access | Health, model listing, generated answer |
| 9. Debrief | Review evidence and unverified integration work | Next-run decision |

### Files

Paths below are relative to `workshops/email-multilora`:

| File | Purpose |
| --- | --- |
| `scripts/train-nemotron.sh` | Dataset-gated MLX-LM LoRA launcher |
| `config/nemotron_mlx_lora.yaml` | Conservative starting hyperparameters |
| `scripts/check-nemotron-lora.py` | Tiny BF16 backward/optimizer diagnostic |
| `scripts/serve-nemotron.sh` | Optional vLLM-Metal inference server |
| `scripts/smoke-nemotron.py` | Health, model discovery, and chat API check |

The runtime is Homebrew-managed; weights stay in the Hugging Face cache.
Neither is copied into this repository. Keep generated datasets under `data/`
and runs under `artifacts/`, which are ignored by Git. Do not modify the
tracked reviewed datasets or commit private email, adapters, or credentials.

## Lab 1: Prepare The Mac Environment

Start at the repository root, then enter the workshop directory. Subsequent
commands in this guide start in that workshop directory:

```sh
cd workshops/email-multilora
brew tap vllm-project/vllm-metal https://github.com/vllm-project/vllm-metal
brew install vllm-project/vllm-metal/vllm-metal
export MLX_PYTHON="$(brew --prefix vllm-metal)/libexec/bin/python"
"$MLX_PYTHON" -c 'import importlib.metadata as m; import mlx.core as mx; print("Metal:", mx.metal.is_available()); print({name: m.version(name) for name in ("mlx-lm", "vllm", "vllm-metal")})'
```

Initial validation used MLX-LM 0.32.0, vLLM 0.32.0, and vLLM-Metal 0.32.0.
Homebrew can install a newer release; record versions and rerun the checks
after upgrades. Nemotron-H support in vLLM-Metal is experimental.

Do not install these dependencies into the workshop's existing PEFT `.venv`:
its pinned Transformers/Hub dependencies serve a different execution path.
The Mac launcher discovers Homebrew's Python or accepts `MLX_PYTHON` explicitly.
This runtime is shared with local inference, so upgrades can affect both.

## Lab 2: Identify The Base And Prompt Contract

The provided YAML starts from the official BF16 checkpoint. BF16 and FP16
are distinct 16-bit floating-point formats. This lab does not validate FP16,
native FP8 training, or MLX 8-bit/4-bit QLoRA. MLX affine `8bit` is not FP8.

The model-ID default follows the Hub's current revision and is suitable for
exploration, not sufficient lineage for a reproducible multi-adapter run.
Before real training, review and record an immutable commit SHA. To use that
same snapshot for every adapter, explicitly download it with the installed
Hub library, replacing the placeholder with your reviewed SHA:

```sh
export NEMOTRON_REVISION='<reviewed-commit-sha>'
export NEMOTRON_MODEL="$("$MLX_PYTHON" -c 'import os; from huggingface_hub import snapshot_download; print(snapshot_download("nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16", revision=os.environ["NEMOTRON_REVISION"]))')"
```

This downloads weights if they are not cached. Review the model license first.
Record the revision, tokenizer, task instructions, chat-template settings,
data fingerprints, and hyperparameters with each run. Never commit resolved
cache paths. Use the selected snapshot with the launcher's `--model` override.

For reasoning-off experiments, use `enable_thinking=False` consistently during
data formatting and evaluation. Inspect the actual training chat template;
the generic MLX-LM launcher does not inject this keyword into training data.
Do not assume inference-only reasoning controls alter the training template.

## Lab 3: Check LoRA Gradients

If the base configuration is not cached yet, download only that small file:

```sh
"$MLX_PYTHON" -c 'from huggingface_hub import hf_hub_download; hf_hub_download("nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16", "config.json")'
"$MLX_PYTHON" scripts/check-nemotron-lora.py
```

The diagnostic builds a tiny randomly initialized hybrid model, freezes the
base, inserts LoRA into linear layers, verifies finite nonzero gradients, and
performs one Adam step. It does not download full weights, read email, save
a useful adapter, or train the live serving model. The reported
`full_checkpoint_training_verified: false` is intentional.

Discussion: why is a successful backward pass stronger evidence than a
successful inference request, but still insufficient evidence for useful LoRA?

## Lab 4: Prepare Email Supervision

Choose one task: multi-label classification or persona-response writing.
Do not mix their output contracts in one adapter accidentally. Follow the
workshop's [dataset guidance](../README.md#important-correction-this-dataset-is-multi-label)
and [persona evaluation plan](PERSONA_EVALUATION_PLAN.md).

Prepare nonempty `train.jsonl` and `valid.jsonl` under an ignored directory
such as `data/nemotron-mlx/finance`. Each line can use chat messages:

```json
{"messages":[{"role":"user","content":"Reviewed email input and task instructions"},{"role":"assistant","content":"Reviewed target answer"}]}
```

This is a schema illustration, not workshop training data. No new dataset
is supplied by this lab. The launcher checks file presence, not content
quality, split leakage, template correctness, or all JSONL schema constraints.

Before training:

- Remove or obtain approval for private identifiers and email content.
- Split by stable email/conversation identity; keep exact duplicates out of
  different splits and never use final-test data for training or tuning.
- For classification, preserve multiple labels and specialist negative
  examples. For persona writing, use reviewed replies and stable client IDs.
- Inspect tokenizer output and completion-only masking with the exact model.
  `mask_prompt: true` requests prompt masking; verify the actual supervised
  tokens before claiming the intended reasoning or answer-only contract.
- Record data checksums, split lineage, and truncation rates. The starting
  context is 512 tokens; long emails can lose essential supervision.

## Lab 5: Train One Adapter

Stop the inference server with Ctrl+C before full-checkpoint training to free
memory. The launcher warns but does not stop other processes automatically.

First run a short real-data smoke with a new output directory:

```sh
sh scripts/train-nemotron.sh \
  data/nemotron-mlx/finance artifacts/nemotron-mlx/finance-smoke \
  --model "$NEMOTRON_MODEL" --iters 2 --save-every 2
```

Then, only after reviewing loss, supervised tokens, memory, and saved output,
start an independent longer experiment:

```sh
sh scripts/train-nemotron.sh \
  data/nemotron-mlx/finance artifacts/nemotron-mlx/finance-run-01 \
  --model "$NEMOTRON_MODEL"
```

The default is rank 8, the final eight blocks, BF16 base weights, batch 1,
gradient accumulation 4, learning rate 0.00001, 512-token sequences, gradient
checkpointing, and 100 iterations. These are starting values, not a validated
email training recipe. A smoke run does not demonstrate quality gains.

Dataset and output paths are resolved from the workshop root even when the
launcher is invoked elsewhere. It rejects missing/empty splits and an existing
adapter output path. Do not override its `--data`, `--config`, or
`--adapter-path` options through appended CLI arguments; those would bypass
the checked paths. Choose a new run directory for each experiment.

Adapters are saved to the selected artifact directory; cached base weights
are not overwritten. This lab does not provide automatic resume, adapter
hash manifests, or integration with the existing persona pipeline.

## Lab 6: Evaluate Before Serving

Use MLX-LM directly to check the trained adapter against the same base:

```sh
"$MLX_PYTHON" -m mlx_lm generate \
  --model "$NEMOTRON_MODEL" \
  --adapter-path artifacts/nemotron-mlx/finance-run-01 \
  --prompt 'A reviewed held-out evaluation prompt' --max-tokens 128
```

Repeat without `--adapter-path` for the base comparison. Use the same reviewed
prompt formatting, decoding settings, token budget, and held-out examples.
The single command above is a functional check, not a full evaluation harness.

For classification, review multi-label accuracy, minority-label recall, invalid
JSON, off-domain negatives, and routing coverage. For persona responses,
review groundedness, style, privacy, hallucinations, and blinded paired human
judgments as described in the evaluation plan. Tune only on validation data;
keep the final test sealed until the experiment protocol is frozen.

## Lab 7: Plan Multiple Adapters

Repeat Lab 5 for another reviewed client/domain using independent data and
output directories but the exact same base revision and tokenizer. For example,
use `data/nemotron-mlx/travel` with `artifacts/nemotron-mlx/travel-run-01`.

Keep model identity, target layers, rank, training configuration, prompt
contract, and evaluation rows comparable. Multi-LoRA means selecting among
separate compatible adapters, not merging client knowledge or stacking all
adapters into one reply. The supplied server does not register adapters.

MLX adapters are not automatically PEFT/vLLM-compatible. Before deployment,
validate format, target names, runtime support, and switching behavior. An
MLX-LM fuse/export step may produce one standalone adapted checkpoint, but
that is not proof of multi-adapter serving. The existing workshop's PEFT
manifests and vLLM registration path remain separate and unchanged.

## Lab 8: Optional Inference And LAN Access

After training is stopped, start the base-model API in one terminal:

```sh
sh scripts/serve-nemotron.sh
```

This serves `nemotron-local` on `http://127.0.0.1:8000/v1`, with an interactive
schema at `http://127.0.0.1:8000/docs`. `NEMOTRON_MODEL` selects the base or
an explicitly verified standalone checkpoint; the script does not load LoRA
adapters. The server uses a 4096-token context, up to two sequences, FP32
Mamba state, and a 50% device-memory budget. That budget is not a hard
process-wide memory limit. Set `NEMOTRON_PORT` to change the port.

From another terminal, starting at the workshop directory:

```sh
python3 scripts/smoke-nemotron.py
```

This checks `/health`, `/v1/models`, and a generated `4` for `2 + 2`. It does
not measure email accuracy or demonstrate that a trained adapter was used.

For trusted-LAN access, stop the localhost server, then restart it with:

```sh
NEMOTRON_HOST=0.0.0.0 sh scripts/serve-nemotron.sh
```

All IPv4 interfaces are now bound. There is **no authentication or TLS**;
reachable devices can consume GPU resources and traffic is unencrypted.
Use only on a trusted network; do not forward port 8000 to the internet.
Use authentication and TLS or an authenticated encrypted tunnel on untrusted
networks. A macOS firewall prompt or Wi-Fi client isolation can block access.

Discover the current machine's name and address rather than assuming a fixed IP:

```sh
scutil --get LocalHostName
ipconfig getifaddr en0
NEMOTRON_BASE_URL="http://$(scutil --get LocalHostName).local:8000" \
  python3 scripts/smoke-nemotron.py
```

Initial host verification passed using `mastersmac` and `mastersmac.local`.
`mastermac.local` did not resolve: it omits the `s`. Other participants must
use their own hostnames, and another device's DNS/mDNS support may differ.
Stop the server with Ctrl+C. No automatic login service is installed.

## Lab 9: Evidence And Next Steps

Observed on 2026-10-21:

- BF16 tiny random Nemotron-H LoRA gradients and one Adam update passed.
- vLLM-Metal served the official 4B BF16 checkpoint on the Mac GPU.
- Localhost, LAN-address, and hostname health/model/chat checks passed from
  the host Mac; another device was not tested.
- Shell syntax, launcher guards, and source-relative configuration are checked
  separately from model-quality claims.

Remaining participant plan:

1. Review and pin the base revision; audit the prompt/template contract.
2. Prepare authorized, leakage-checked train/validation email data.
3. Stop inference; perform a bounded full-checkpoint LoRA smoke.
4. Train one adapter, then compare it with the base on held-out inputs.
5. Train a second compatible adapter and record comparable lineage.
6. Validate adapter export/loading and switching before multi-LoRA serving.

Not yet demonstrated: real-data/full-checkpoint LoRA training, adapter quality
improvements, native FP16/FP8 training, MLX-to-PEFT conversion, vLLM adapter
loading, or simultaneous multi-adapter serving. No cloud training or deployment
was performed for this Mac lab.

For larger NVIDIA experiments, the official
`nvidia/NVIDIA-Nemotron-Nano-9B-v2` BF16 and
`nvidia/NVIDIA-Nemotron-Nano-9B-v2-FP8` mixed FP8/BF16 inference checkpoints
are separate options, not deployed by this lab. BF16/FP16 training can use a
compatible Transformers/PEFT or NeMo recipe. Native NVIDIA FP8 mixed-precision
training requires supported GPU hardware and a compatible NeMo/Megatron-Core
and Transformer Engine recipe; an FP8 inference checkpoint is not that recipe.

## References

- [MLX-LM](https://github.com/ml-explore/mlx-lm)
- [vLLM-Metal model support](https://docs.vllm.ai/projects/vllm-metal/en/latest/supported_models/)
- [Nemotron 3 Nano 4B BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16)
- [Nemotron Nano 9B v2 BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2)
- [Nemotron Nano 9B v2 FP8](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2-FP8)
- [vLLM FP8 hardware support](https://docs.vllm.ai/en/latest/features/quantization/llm_compressor/fp8/)