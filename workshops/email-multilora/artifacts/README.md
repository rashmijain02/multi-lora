# Trained adapter artifacts: inventory and reuse guide

This directory holds **local experiment outputs**, not standalone pretrained language models.
The pretrained base comes from Hugging Face; our training produced small LoRA weight updates.
To generate replies you need **the exact base revision + the matching adapter + the original
persona prompt/tokenizer**. An adapter alone cannot generate text.

Only this README is intended for Git. Model weights, checkpoints, predictions, logs, and
executed notebook copies remain ignored. **Cloning the repository does not download these
trained adapters.** The relative run links below work only after the corresponding artifacts
have been supplied locally.

## Contents

1. [Choose the right run](#choose-the-right-run)
2. [Understand the files](#understand-the-files)
3. [Reuse a persona adapter locally](#reuse-a-persona-adapter-locally)
4. [Select another client](#select-another-client)
5. [Compare and evaluate](#compare-and-evaluate)
6. [Reuse classification adapters](#reuse-classification-adapters)
7. [Serve multiple persona adapters](#serve-multiple-persona-adapters)
8. [Transfer to another machine](#transfer-to-another-machine)
9. [Retention and troubleshooting](#retention-and-troubleshooting)

## Choose the right run

Inventory describes the runs created during the workshop; it is not a model registry or a
production certification. Sizes are approximate and can change after evaluation.

| Local directory | Task and base | Contents | Reuse recommendation |
|---|---|---|---|
| [persona-qwen2.5-3b-full/](persona-qwen2.5-3b-full/) | **Persona email replies**, Qwen2.5 3B Instruct | Ten client adapters, paired predictions, pipeline summaries; about 436 MiB total | **Start here for reply writing** |
| [persona-qwen2.5-3b-smoke/](persona-qwen2.5-3b-smoke/) | Persona replies, Qwen2.5 3B | One-step Maya check using eight training rows | Debugging only, not quality evidence |
| [local-full-20261018/](local-full-20261018/) | Multi-label classification, Qwen2.5 0.5B | Four adapters and 312-row validation predictions; about 98 MiB | Classification study |
| [local-smoke-20261018/](local-smoke-20261018/) | Classification, Qwen2.5 0.5B | Small training/loading check | Debugging only |
| [nemotron-nano-8b-full-20261018/](nemotron-nano-8b-full-20261018/) | Classification, NVIDIA Nemotron Nano 8B | Four adapters and full-validation predictions; about 278 MiB | Historical classification study; read [NVIDIA findings](../docs/NEMOTRON_LORA_FINDINGS.md) |
| [nemotron-nano-8b-smoke-20261018/](nemotron-nano-8b-smoke-20261018/) | Classification, Nemotron Nano 8B | Small training/loading check | Debugging only |
| [run-2026/](run-2026/) | Prepared classification data | Splits and data manifest; no trained adapters | Notebook preparation output |
| [persona-lora-run-2026/](persona-lora-run-2026/) | Persona preparation | Data handoff only; no trained adapters | Not an inference run |
| [notebook-validation/](notebook-validation/) | Notebook checks | Executed copies, reports, scratch runs | Regenerable validation output |

Classification adapters return label arrays; persona adapters return reply text. They are not
interchangeable. The generic baseline CSV is not an eleventh trained persona adapter in the
current [client registry](../config/persona_registry.json).

### Current reply-writing model

The completed persona run uses:

- Base: `Qwen/Qwen2.5-3B-Instruct`.
- Revision: `aa8e72537993ba99e69dfaafa59ed015b17504d1`.
- LoRA rank: 8; targets: `q_proj`, `v_proj`.
- Training: one epoch, learning rate `2e-4`, batch size 1, gradient accumulation 8.
- Context: 1,024 tokens.
- Per client: 1,473 training rows, 312 validation rows, 318 held-out test rows.
- Original local hardware: RTX 3090 with 24 GiB VRAM.

These settings describe this run, not universal minimum hardware requirements. Do not load these
adapters onto Qwen 0.5B, Qwen 7B, Nemotron, or a different base revision.

## Understand the files

Example run: [persona-qwen2.5-3b-full/](persona-qwen2.5-3b-full/).

| Location/file | Purpose | Required for ordinary inference? |
|---|---|---|
| [persona_adapters/](persona-qwen2.5-3b-full/persona_adapters/) | One directory per trained client | Yes, selected client directory |
| `adapter_model.safetensors` | Learned LoRA weights; about 7.05 MiB per Qwen 3B client | Yes |
| `adapter_config.json` | Base identity and PEFT configuration | Yes |
| `manifest.json` | Dataset/profile identity, config, metrics, versions, hashes, training history | Yes for workshop verification |
| Tokenizer files and `chat_template.jinja` | Tokenization, special tokens, chat rendering | Keep all supplied tokenizer files |
| `training_args.bin` | Serialized training arguments | Not needed for inference |
| Adapter `README.md` | PEFT-generated model-card metadata | Useful provenance |
| `checkpoints/checkpoint-*` | Training state, adapter snapshot, optimizer, scheduler, RNG, Trainer history | No; retain for training-state recovery |
| [persona_evaluation/](persona-qwen2.5-3b-full/persona_evaluation/) | Reference/generated replies and inference contracts | No; keep for audit/comparison |
| [persona_pipeline/status.json](persona-qwen2.5-3b-full/persona_pipeline/status.json) | Latest orchestration state | No; keep for run tracking |
| [persona_pipeline/result.json](persona-qwen2.5-3b-full/persona_pipeline/result.json) | Completed configuration and per-client metrics | No; keep as run summary |

Each full persona directory occupies about **43.5 MiB including its checkpoint**. This is larger
than its LoRA weights because it also contains tokenizer assets and optimizer/checkpoint state.
The sum for ten adapters is about 435 MiB, plus evaluation outputs.

The workshop verifier checks hashes for five files: adapter config, adapter weights,
`tokenizer.json`, `tokenizer_config.json`, and `special_tokens_map.json`. It also checks client
identity and data/profile lineage. It does **not** authenticate the publisher, checksum every
checkpoint file, or prove response quality. Obtain bundles only from a trusted source; treat
pickle-based training-state files as untrusted code-bearing data.

## Reuse a persona adapter locally

### Step 1: obtain the code and artifacts

Use a matching checkout containing the [workshop package](../email_workshop/),
[registry](../config/persona_registry.json), [persona profiles](../data/personalities/),
and [reviewed CSVs plus their manifest](../data/manual_full_response/).
Place the supplied complete run under this directory, retaining its layout.

The high-level loader deliberately requires the original data and profiles to verify provenance,
even though model generation itself does not need training examples.

### Step 2: prepare the environment

From the repository root, run in PowerShell:

```powershell
Set-Location .\workshops\email-multilora
.\scripts\setup-local.ps1 -Device cuda -Python python
.\scripts\setup-local.ps1 -Device cuda -CheckOnly
```

Use the approved Python 3.12 installation on your machine. The setup script installs the pinned
training stack and registers the workshop notebook kernel. It does not train any adapter.
See [local setup](../docs/LOCAL_SETUP.md) for CPU and Linux/WSL instructions.

Do not copy another machine's `.venv`. In VS Code select **Python (email-multilora)**, not a parent
workspace environment. A CPU run is supported via `device="cpu"` but uses FP32 and can be slow.

### Step 3: verify the saved adapter without loading the base

Run the following Python from the workshop environment, in a notebook or Python script:

```python
from pathlib import Path
import email_workshop
from email_workshop.persona import verify_persona_adapter

workshop = Path(email_workshop.__file__).resolve().parents[1]
run = workshop / "artifacts" / "persona-qwen2.5-3b-full"
client_id = "maya-chen-ceo"

manifest = verify_persona_adapter(run, workshop, client_id)
if manifest["purpose"] != "workshop":
    raise ValueError("Select a full workshop adapter, not a smoke adapter.")
print(manifest["config"]["model_id"])
print(manifest["config"]["model_revision"])
```

Stop on a verification error. Do not edit hashes, disable checks, or substitute another base to
make the check pass.

### Step 4: generate a reply

Continue in the same Python session:

```python
from email_workshop.persona import PersonaBackend

backend = PersonaBackend(run, workshop, client_id, device="cuda")
reply = backend.generate(
    subject="Project review: owner and next milestone",
    body=(
        "The launch review is pending. We need a named owner and the next milestone "
        "before deciding whether to expand the pilot. What should we send you?"
    ),
    adapted=True,
)
print(reply)
```

The first load downloads the pinned base if it is absent from the Hugging Face cache. No Foundry,
Azure endpoint, or `.env` credentials are required. Internet may still be needed for initial
package/model downloads. For offline operation, preload the exact base revision and dependencies
and set `HF_HUB_OFFLINE=1` before starting Python; missing cache entries should fail explicitly.

`PersonaBackend`:

- Loads the saved tokenizer and verifies the adapter against the original CSV/profile.
- Adds the persona's name, role, style, and boundaries to the system prompt.
- Uses the original subject/body prompt and chat template.
- Truncates the email to fit the prompt budget; it is not full-thread retrieval.
- Generates greedily (`do_sample=False`) with at most 192 new tokens.
- Uses BF16 on a compatible CUDA device, otherwise FP32.
- Returns only generated reply text; it does not send email or execute requested actions.

For the 1,024-token run, the prompt budget is 832 tokens, including the profile and chat
template. Long threads can lose information; inspect truncation before relying on a reply.

### Step 5: compare to the unadapted base

```python
base_reply = backend.generate(
    subject="Project review: owner and next milestone",
    body=(
        "The launch review is pending. We need a named owner and the next milestone "
        "before deciding whether to expand the pilot. What should we send you?"
    ),
    adapted=False,
)
print(base_reply)
```

`adapted=False` disables LoRA **but keeps the same persona prompt**. This isolates the effect of
the trained adapter rather than comparing different prompts.

## Select another client

Use the registry's client ID, not a CSV filename or adapter-directory name:

| Client ID | Display name | Adapter directory |
|---|---|---|
| `maya-chen-ceo` | Maya Chen | `maya-chen` |
| `daniel-okafor-cfo` | Daniel Okafor | `daniel-okafor` |
| `priya-raman-support` | Priya Raman | `priya-raman` |
| `lucas-silva-engineer` | Lucas Silva | `lucas-silva` |
| `amina-yusuf-sales` | Amina Yusuf | `amina-yusuf` |
| `jordan-lee-people-ops` | Jordan Lee | `jordan-lee` |
| `elena-petrova-marketing` | Elena Petrova | `elena-petrova` |
| `marcus-green-legal` | Marcus Green | `marcus-green` |
| `sofia-alvarez-operations` | Sofia Alvarez | `sofia-alvarez` |
| `noah-williams-assistant` | Noah Williams | `noah-williams` |

Change `client_id` before creating the backend. Each `PersonaBackend` loads one base plus one
adapter; creating ten instances retains ten base copies and can exhaust VRAM. Use separate
processes sequentially for simple local testing, or the shared serving route below.
Do not concurrently call a single backend while changing adapter state.

## Compare and evaluate

Use [notebook 06](../notebooks/06_compare_persona_responses.ipynb) for response comparison and
adapter inventory. Use [notebook 07](../notebooks/07_persona_evaluation_techniques.ipynb) and
the [evaluation plan](../docs/PERSONA_EVALUATION_PLAN.md) for the full quality protocol.

The saved persona prediction files currently cover **eight validation emails per client**,
not all 312 validation emails. Training checkpoint selection did use the full validation set.
The saved response diagnostics are token F1, ROUGE-L, exact match, non-empty rate, length ratio,
and latency. They are not validated measures of persona fidelity, truthfulness, or safety.

Next gates: full validation, blinded human A/B rubric review, reviewed risk flags, robustness
challenges, and then a final test after settings are frozen. Do not use the test set repeatedly
to tune prompts or hyperparameters. Do not enable final-test cells merely to try inference.

## Reuse classification adapters

Use the earlier runs only for predicting labels, not writing persona replies.
For example, from the workshop directory:

```powershell
.\.venv\Scripts\python.exe -m email_workshop.cli `
  --artifacts artifacts/local-full-20261018 `
  evaluate --device cuda --split validation
```

This loads the saved four adapters and evaluates base, generalist, all-specialist, and routed
strategies. Matching prediction checkpoints can be reused; missing predictions trigger local
inference. No training is performed. Do not add a different `--limit` to an existing prediction
path: its fingerprint binds it to the original ordered evaluation IDs.

Classification run layout:

- `data/`: prepared train/validation/test rows and their manifest.
- `adapters/`: generalist, operations, finance, and travel adapter directories.
- `router/`: fitted threshold metadata and lexical validation metrics; the router is
  deterministically refitted from train/validation rather than loaded from a pickle.
- `evaluation/`: prediction checkpoints and corresponding `.metrics.json` files.
- Logs and Markdown run reports: historical diagnostic evidence.

Use [notebook 03](../notebooks/03_compare_and_serve.ipynb) for individual classification examples.
Keep each run's own base, tokenizer, prompt, router, and data together. Historical Nemotron
results do not establish current NIM profile compatibility.

## Serve multiple persona adapters

For a shared-base Multi-LoRA server, [notebook 06](../notebooks/06_compare_persona_responses.ipynb)
provides the inventory and command-generation path. Generate, inspect, and transfer a command:

```python
import shlex
from email_workshop.persona import persona_vllm_command

command = persona_vllm_command(
    run,
    workshop,
    linux_run_root="artifacts/persona-qwen2.5-3b-full",
)
print(shlex.join(command))
```

This **prints a Linux command; it does not start a server**. Run it from the corresponding
workshop directory in a separate, compatible Linux/WSL2 vLLM environment after transferring the
artifacts. Do not replace the Windows workshop environment with vLLM dependencies.

The command pins the base revision, enables LoRA, registers verified adapter names, and binds to
`127.0.0.1:8000`. Keep it private. A client must select the registered adapter name and send the
same persona/chat-template prompt; a bare email sent as a prompt does not reproduce training.
Use `persona_messages`/`persona_prompt_ids` from the workshop rather than inventing a new prompt.

Command generation and local PEFT loading were verified; this README does not claim that a live
vLLM server or concurrent shared GPU batches were tested for these artifacts. Verify model,
adapter rank/target compatibility, context limits, memory, and prompt behavior in your chosen
vLLM version. These artifacts are not automatically Foundry or NVIDIA NIM deployments.

## Transfer to another machine

1. Record the Git commit of the code, registry, profiles, and reviewed data.
2. Copy the complete selected run directory, preserving relative layout.
3. Include the matching registry, profiles, reviewed CSVs and data `MANIFEST.json`.
4. Obtain the exact base revision separately under its license; the adapter bundle is not the
   full base model. See the [Qwen model card](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)
   and applicable data/model terms before distributing a bundle.
5. Create a fresh environment using the setup guide. Never transfer a virtual environment.
6. Run `verify_persona_adapter`, then one synthetic-email generation before processing data.
7. Run your evaluation protocol on the new runtime; latency and numerical results may change.

The loaders derive locations from the installed package and selected run path. Historical
pipeline summaries or best-checkpoint fields may contain paths from the original machine;
they are audit metadata, not instructions to recreate that machine's directory.

Do not publish predictions, datasets, logs, or profiles without reviewing their contents and
rights. Evaluation JSON contains both reference replies and generated text. Never include
credentials, private email, or the model cache indiscriminately in a shared archive.

## Retention and troubleshooting

### Keep versus remove

- **Keep:** full persona run, manifests, tokenizers, weights, and evaluation lineage.
- **Archive if useful:** full Qwen/Nemotron classification runs for historical comparisons.
- **Regenerable:** smoke runs, early data-only runs, notebook-validation copies, and console logs.
- **Optional:** checkpoint subdirectories in completed runs if exact Trainer-state recovery is
  no longer required. Back up first; inference uses top-level adapter files, but removing a
  checkpoint breaks its recorded best-checkpoint path. Pipeline restart is not a promise of
  automatic mid-epoch optimizer restoration.

Do not delete an active run or alter top-level files covered by manifest checksums. No cleanup
is performed by this guide.

| Symptom | Next check |
|---|---|
| Artifact directory missing after cloning | Weights are ignored; obtain a trusted artifact bundle or train with notebook 05 / the persona pipeline |
| `torch`, `transformers`, or `peft` missing | Run workshop setup and select its kernel; do not install into a broken parent environment |
| CUDA unavailable | Check the setup script's device test, NVIDIA driver, and CUDA PyTorch build |
| CUDA out of memory | Close your own unused model instances/kernels; avoid multiple base copies; use CPU for a slow sanity check |
| Persona identity/data lineage mismatch | Restore the matching committed CSV, registry, and profile; do not edit the manifest to bypass it |
| Adapter checksum mismatch | Restore trusted original files; investigate incomplete copies or modifications |
| Missing base while offline | Preload the pinned revision in the correct Hugging Face cache |
| Generic, verbose, or off-persona replies | Verify client selection, `adapted=True`, exact base and prompt; inspect outputs with notebook 07 |
| Bad behavior on long threads | Inspect prompt truncation and profile/context budget |
| Need to change a profile or retrain | Create a new versioned dataset/run; preserve the old run for comparison |

These are synthetic workshop personas and experimental adapters, not authorized representatives
of real staff. Keep generated replies as drafts subject to human approval, especially for
financial, legal, HR, sensitive-data, or contractual decisions.
