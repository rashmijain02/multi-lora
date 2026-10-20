# Local LoRA environment setup and execution

All examples start at the `multi-lora` repository root and then enter the workshop.
No Azure account, endpoint, `.env`, or paid cloud resource is needed. This path downloads
the public pinned dataset and the open-weight model selected by a pinned profile, trains four
local LoRA adapters, and evaluates them locally. It does not call Foundry. The accessible
default is Qwen2.5-0.5B. Nemotron Nano 8B is an optional NVIDIA study profile; review
[its LoRA, NIM, prompt-contract, and 24 GB GPU constraints](NEMOTRON_LORA_FINDINGS.md)
before enabling it.

## Requirements

- Python 3.11-3.13 (3.12 recommended), pip and venv support.
- Internet for package/model/dataset downloads; disk space for CUDA PyTorch, model cache,
  checkpoints and artifacts. Allow several GB; CUDA wheels alone are large.
- For CUDA: NVIDIA GPU and driver compatible with the PyTorch CUDA 12.8 wheel.
  The small model is intended for modest GPU workloads; 12-24 GB VRAM is a practical
  starting point, not a measured minimum or guarantee.
- Windows PowerShell or Bash on Linux/WSL. CUDA/CPU wheel setup below targets Windows/Linux,
  not macOS. WSL requires a working GPU passthrough/driver setup first.

These scripts create/reuse `.venv` **inside the workshop**. They never delete environments,
change system Python, or install vLLM. Do not share a Windows `.venv` with Linux/WSL; use
separate checkouts/environments. Shut down notebook kernels using this environment before
replacing PyTorch wheels. Existing unrelated environments remain untouched.

## Windows PowerShell

```powershell
Set-Location .\workshops\email-multilora
# NVIDIA GPU training:
.\scripts\setup-local.ps1 -Device cuda -Python python
# Or CPU-only training/validation (slower):
# .\scripts\setup-local.ps1 -Device cpu -Python python

# Repeat verification without installing/changing dependencies:
.\scripts\setup-local.ps1 -Device cuda -CheckOnly
```

If script execution is blocked, review it and follow your organization's execution policy;
do not weaken the machine-wide policy. `-Python` accepts a Python executable name.
Use a Python 3.12 command available on your PATH.

## Linux / WSL Bash

```bash
cd workshops/email-multilora
bash scripts/setup-local.sh --device cuda --python python3.12
# CPU alternative:
# bash scripts/setup-local.sh --device cpu --python python3.12
bash scripts/setup-local.sh --device cuda --check-only
```

On distributions without venv support, install the matching Python venv package using
your approved OS package manager before retrying.

## What setup does

1. Locates the workshop using the script location; invocation does not depend on a fixed checkout.
2. Creates `.venv` if absent; reports broken/existing incompatible environments instead of deleting them.
3. Installs the exact `torch==2.10.0+cu128` or `torch==2.10.0+cpu` build from PyTorch's index.
   The `+cu128` suffix matters: `torch==2.10.0` alone can leave an already-installed CPU wheel unchanged.
4. Installs the editable workshop with `training,dev` extras and registers an environment-local
   `email-multilora` Jupyter kernel.
5. Runs `pip check`, imports the real training modules, verifies pinned versions, and executes
   a tensor on the selected device. CUDA setup fails if GPU execution is unavailable.

The scripts default to **CPU** unless you explicitly select CUDA. Switching device mode
deliberately replaces the wheel in this workshop environment.

Open `email-multilora.code-workspace` and select the workshop environment in VS Code.
Restart existing kernels after package installation. Environment-local kernel registration
does not silently switch the kernel of an already-open notebook.

## First local smoke: Windows

From the workshop directory, choose a **new** run name; do not overwrite earlier runs:

```powershell
$python = '.\.venv\Scripts\python.exe'
$run = 'artifacts/local-smoke-01'
& $python -m email_workshop.cli --artifacts $run prepare
& $python -m email_workshop.cli --artifacts $run router
& $python -m email_workshop.cli --artifacts $run train --device cuda --max-steps 2 --sample-limit 16
& $python -m email_workshop.cli --artifacts $run evaluate --device cuda --split validation --limit 8 --allow-smoke
```

Stop if any command fails; do not continue to evaluation with missing/partial adapters.
For CPU, replace both `--device cuda` arguments with `--device cpu`.
Preparation downloads public data; training downloads the pinned model if not already cached.
No token is normally required for these public assets. Never print tokens if your network requires one.

## First local smoke: Linux / WSL

```bash
set -e
run=artifacts/local-smoke-01
.venv/bin/python -m email_workshop.cli --artifacts "$run" prepare
.venv/bin/python -m email_workshop.cli --artifacts "$run" router
.venv/bin/python -m email_workshop.cli --artifacts "$run" train --device cuda --max-steps 2 --sample-limit 16
.venv/bin/python -m email_workshop.cli --artifacts "$run" evaluate --device cuda --split validation --limit 8 --allow-smoke
```

Smoke training performs real optimizer steps, saves all four adapters, and tests model loading
and evaluation. It is **not useful classification-quality evidence**. Evaluation compares
base, generalist, all-specialist and routed strategies on identical rows.

## Full training and validation

After the smoke succeeds, use a separate fresh run:

```powershell
$run = 'artifacts/local-full-01'
& $python -m email_workshop.cli --artifacts $run prepare
& $python -m email_workshop.cli --artifacts $run router
& $python -m email_workshop.cli --artifacts $run train --device cuda --epochs 2
& $python -m email_workshop.cli --artifacts $run evaluate --device cuda --split validation
```

On Linux, use `.venv/bin/python` with the same CLI arguments. Freeze configuration and
validation decisions before running the final `--split test` comparison. Do not repeatedly
tune against the test split. Full evaluation time depends on generation lengths and the GPU;
no runtime or quality improvement is guaranteed.

### Run the same cycle with another compatible base

Both the individual `train` command and staged pipeline use model profiles. Verify the
architecture, license, chat template, target modules and hardware fit before a full run.
Never use a floating model revision for a comparison.

Example using the locally validated NVIDIA model:

```powershell
$run = 'artifacts/nemotron-nano-8b-full-20261018'
& $python -m email_workshop.pipeline `
  --profile full `
  --device cuda `
  --artifacts $run `
  --model-profile nemotron-nano-8b `
  --run
```

This remains local PEFT training. It does not call the separately documented Foundry
managed-compute deployment. Use a fresh artifact root per model/configuration.

For an unlisted model, select `--model-profile custom` and provide `--model-id`,
`--model-revision` and `--target-modules`. Start with a smoke run. A generic Hugging Face
repository is not automatically compatible merely because it is open weight.

## Outputs and checks

Within each ignored run directory:

- `data/`: local splits and manifest; email text stays local.
- `router/`: selected routing configuration and validation metrics.
- `adapters/`: generalist, operations, finance and travel weights, checkpoints, tokenizer and manifests.
- `evaluation/`: resumable predictions and per-label/summary metrics.

Trackio is initialized for local runs without a hosted space. Do not upload dataset text,
prediction artifacts, adapters or credentials automatically.

```powershell
& $python -m pytest tests -q
& $python -m ruff check email_workshop tests scripts
```

The GPU training process is not a server: it exits after saving results. For notebook use,
set `EMAIL_WORKSHOP_RUN` to the relative run directory **before starting the kernel**.
For vLLM serving use the separate Linux/WSL lab in the workshop README; do not install it
into this Windows training environment.

## Troubleshooting

- **CUDA false / CPU wheel:** run the CUDA setup, not just `pip install torch==2.10.0`;
  inspect driver visibility with `nvidia-smi`, then use `-CheckOnly` / `--check-only`.
- **Broken .venv from another machine:** inspect it and explicitly recreate only the
  workshop environment. These scripts intentionally do not delete it.
- **Out of memory:** inspect other GPU workloads; do not kill unrelated processes.
  Start with the smoke and use CPU if necessary.
- **Download blocked:** resolve proxy/CA/cache access through approved settings; do not
  disable TLS verification.
- **Run already exists:** pick a new run directory; preparation/adapters refuse overwrite.
- **Missing imports in notebook:** select the workshop kernel and restart it.
- **Incomplete/invalid model JSON:** review the recorded valid/invalid metrics. Outputs
  are scored honestly, not silently repaired or substituted.
