# PersonaDesk on NVIDIA DGX Spark: full-experience guide

This guide runs every PersonaDesk phase on one DGX Spark with local models only:

| Role | Process | Port (loopback only) |
|------|---------|----------------------|
| Controller (Hermes's model; plans, calls tools) | vLLM, tool-calling model | `8000` |
| Writer (persona voice; base model + LoRA adapters) | vLLM Multi-LoRA | `8001` |
| Writer service (registry check, adapter lineage) | `scripts/writer_service.py` | `8100` |
| CLM encoder (Qwen3-8B embeddings) | vLLM `--runner pooling` | `8090` |
| CLM API (typed classification answers) | `clm-serve` | `8700` |
| Agent runtime | Hermes Agent + `personadesk` plugin | — |

The development machine (RTX 3080 10 GB) covers the CPU and fake-worker phases. Spark adds:
- a real local controller;
- persona adapters trained on CUDA and served together;
- a real CLM backend instead of mock mode.

Read [PROPOSAL.md](../PROPOSAL.md) for the design and [LEARNING_PLAN.md](../LEARNING_PLAN.md) for
the phases. Commands below run on the Spark in a Linux shell. Each code block states its starting
directory. Paths are relative to the repository root unless they start with `~`.

> **Security baseline.** Every server in this guide binds to `127.0.0.1` or publishes Docker
> ports as `127.0.0.1:<port>`. None of them authenticate requests. Reach them from a laptop with
> an SSH tunnel (see [§10](#10-remote-access-from-a-laptop)), never by binding to `0.0.0.0`.
> `clm-serve` defaults to `--host 0.0.0.0`, so this guide always passes `--host 127.0.0.1`.

---

## 0. What you need

| Item | Check |
|------|-------|
| DGX Spark (GB10, 128 GB unified memory; a 64 GB variant works with the phased plan in §1) | `nvidia-smi` lists the GB10 GPU |
| DGX OS with Docker and the NVIDIA Container Toolkit | `docker run --rm --gpus all ubuntu nvidia-smi` |
| Hugging Face account and token (model downloads) | `hf auth whoami` |
| `git`, `curl`, `uv` | `uv --version` |
| About 150 GB free disk space for models, adapters, and containers | `df -h ~` |

NVIDIA's own playbooks are the source of truth for container images and model recipes. This
guide links to them rather than pinning image tags that go stale:

- vLLM on Spark: <https://build.nvidia.com/spark/vllm>
- Hermes Agent on Spark: <https://build.nvidia.com/spark/hermes-agent>
- Model recipes (pick DGX Spark, vLLM, your memory size): <https://nvidia.github.io/local-ai-inference-recipes/>

Install `uv` if it is missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Clone the repository with its CLM submodule:

```bash
git clone --recurse-submodules <your-fork-url> multi-lora
cd multi-lora
git submodule update --init --recursive   # if the clone was made without submodules
```

All later blocks start in this repository root unless stated otherwise.

---

## 1. Memory budget

Spark's CPU and GPU share one pool of LPDDR5x memory. vLLM's `--gpu-memory-utilization` is a
fraction of **total** memory, and each vLLM process reserves its fraction at start. The fractions
of all running processes, plus the OS and Hermes, must fit. On unified memory, `nvidia-smi` may
not report per-process memory; use `free -h` and the vLLM startup log
(`Available KV cache memory`) instead.

### 128 GB plan (everything resident)

| Process | Example model | `--gpu-memory-utilization` | Approx. reserved |
|---------|---------------|----------------------------|------------------|
| Controller | NVIDIA recipe's recommended tool-calling model (NVFP4) | `0.40` | ~51 GB |
| Writer | `Qwen/Qwen2.5-7B-Instruct` BF16 + 3 rank-8 adapters | `0.20` | ~25 GB |
| CLM encoder | `Qwen/Qwen3-8B` BF16, pooling | `0.15` | ~19 GB |
| OS, Hermes, Python, page cache | — | — | remaining ~33 GB |

Start the processes in this order (largest first), and wait for each to report ready.

**Training is a separate phase.** A 7B BF16 LoRA training run needs roughly 25–35 GB. Stop the
writer vLLM (and, if needed, the CLM encoder) while training, then restart them.

### 64 GB plan (phased)

Run one phase at a time instead of keeping everything resident:

| Phase | Running |
|-------|---------|
| Controller + writer | Controller at `0.45`, writer `Qwen2.5-3B-Instruct` at `0.20` |
| Classification | CLM encoder at `0.35` + `clm-serve`; stop the writer |
| Training | Training only; stop all vLLM processes |

The CLM reference head is trained on Qwen3-8B embeddings. Do not swap in a smaller encoder,
because its scores would be meaningless.

---

## 2. Python environments

Two environments are used. Neither needs `sudo`.

```bash
# PersonaDesk plugin, CLI, tests, K0 baseline (CPU only)
cd workshops/personal-agent-multilora
uv sync --extra dev --extra classification
uv run pytest -q          # expect: all tests pass, no GPU needed
cd ../..
```

```bash
# Email workshop: data preparation, persona adapter training, writer service (CUDA)
cd workshops/email-multilora
uv sync --extra training --extra dev
uv run python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
cd ../..
```

The second check must print `True` and the GB10 device. Spark is **aarch64**. If the pinned
`torch` wheel has no CUDA build for aarch64 (`is_available()` prints `False`), train inside
NVIDIA's PyTorch container instead. It ships a Blackwell-enabled PyTorch build:

```bash
# start in the repository root; pick the current tag from NGC (nvcr.io/nvidia/pytorch)
docker run --rm -it --gpus all --ipc=host \
  -v "$PWD":/workspace/multi-lora -v ~/.cache/huggingface:/root/.cache/huggingface \
  -w /workspace/multi-lora/workshops/email-multilora nvcr.io/nvidia/pytorch:<tag> bash
# inside the container: keep the container's torch, add the rest
pip install -e . "transformers==4.57.6" "peft==0.18.1" "accelerate==1.12.0" "trackio==0.7.0"
```

Use the same container for the training commands in §5.

---

## 3. Controller model (vLLM on :8000)

Follow the **vLLM playbook** (<https://build.nvidia.com/spark/vllm>) and pick the recipe it
recommends for your memory size. The model must support **tool calling**. Keep the recipe's
`--enable-auto-tool-choice`, `--tool-call-parser`, and `--reasoning-parser` flags, because Hermes
relies on structured `tool_calls`. Adjust only the following:

- publish the port to loopback: `-p 127.0.0.1:8000:8000`;
- set `--gpu-memory-utilization 0.40` (128 GB plan);
- set `--max-model-len` to at least `32768`. Hermes's system prompt plus tool schemas is large.

Verify (in another terminal):

```bash
curl -sS http://127.0.0.1:8000/health && echo OK
curl -sS http://127.0.0.1:8000/v1/models | python3 -m json.tool   # note the served model id
```

Tool-calling check: the response must contain `tool_calls`, with `finish_reason` `tool_calls`.

```bash
MODEL=<served-model-id>
curl -sS http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model": "'"$MODEL"'",
  "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
  "tools": [{"type": "function", "function": {"name": "get_weather",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}]
}' | python3 -m json.tool
```

If `tool_calls` is missing, the parser flags do not match the model. Fix that before continuing:
PersonaDesk is tool-only, so a controller that cannot call tools produces no drafts.

---

## 4. Hermes Agent and the PersonaDesk plugin

Install Hermes using the Hermes playbook (<https://build.nvidia.com/spark/hermes-agent>), choosing
**Blank Slate** and **Custom endpoint** `http://localhost:8000/v1`. On Linux, the Hermes home is
`~/.hermes`. Confirm that the default profile can reach the controller:

```bash
hermes -z "Reply exactly HERMES_OK"
```

Validate the plugin before wiring it:

```bash
cd workshops/personal-agent-multilora
hermes plugins validate hermes_plugin
PERSONADESK_ROOT="$PWD" hermes plugins doctor hermes_plugin   # expect 5 tools, 1 hook
```

`doctor` copies the plugin to a temporary home. `PERSONADESK_ROOT` tells it where the workshop's
config and fixtures live.

Create the operator allowlist. Only listed OS users can review drafts:

```bash
cp config/operators.example.json config/operators.json
# edit config/operators.json: replace "your-os-username" with the output of `whoami`
```

Wire Hermes: link the plugin, create one isolated profile per enabled persona, and apply the
governance settings. The script prints its plan first; read it, then apply:

```bash
uv run python scripts/setup_hermes.py \
  --model <served-model-id> --base-url http://127.0.0.1:8000/v1
uv run python scripts/setup_hermes.py --apply \
  --model <served-model-id> --base-url http://127.0.0.1:8000/v1
```

For each of `pd-priya`, `pd-daniel`, and `pd-noah`, the script does the following:
- creates the profile with `--no-skills`, never cloned from `default`, so no memories or secrets
  leak in;
- sets `memory.write_approval` and `skills.write_approval` to `true`;
- sets `curator.enabled` and `auxiliary.background_review.enabled` to `false`;
- installs the persona `SOUL.md`, backing up any existing one;
- enables the `personadesk` plugin.

It starts with `--writer template` (deterministic, no GPU). §6 switches it to `http`.

> **Job binding.** Hermes runs every session inside its gateway process, so the worker's
> environment never reaches the plugin. Each job attempt therefore gets a one-time job token. The
> token is placed in the worker's query, and only its SHA-256 digest is written to
> `artifacts/locks/active-job.json`, which exists only while the job runs. `pd_draft_reply`
> accepts a draft only if the token matches, the job is `running`, and the job belongs to this
> persona and fixture.

### E0 → E1: first real run (template writer)

```bash
cd workshops/personal-agent-multilora
uv run personadesk --profile pd-priya run --fixture priya-001
uv run personadesk --profile pd-priya status
uv run personadesk --profile pd-priya show <job-id>          # prints the draft and its hash
uv run personadesk --profile pd-priya review <job-id> \
  --draft-hash <hash> --decision approve --learning-consent
```

`run` launches `hermes -p pd-priya chat --oneshot` as a bounded worker. Its limits are
`max_turns`, a timeout, and a global lock. The tool-call evidence is recorded. Compare with the
fake-worker run from the development machine:
- the job state machine and review flow are identical;
- only the controller is real now.

Then try:
- `pd-daniel` and `pd-noah`;
- a cross-persona fixture, which must be denied;
- a task outside the grant, which must be denied.

### E1 with real mail (local simulator)

Run the loopback mail server in its own terminal, seed it, and let intake create jobs from the
persona's mailbox (details in the workshop README, "Local mail simulation"):

```bash
cd workshops/personal-agent-multilora
uv run pd-mail serve                                  # terminal 1
uv run pd-mail seed                                   # terminal 2
uv run personadesk --profile pd-priya intake --run
```

The server listens on `127.0.0.1` only. For laptop access, tunnel ports 2525 and 1143 over SSH
as in section 10 rather than binding them to the network.

---

## 5. Persona writer adapters (training on CUDA)

Prepare the email data once (writes `artifacts/run-2026`), then review the persona pipeline plan:

```bash
cd workshops/email-multilora
uv run python -m email_workshop.cli --artifacts artifacts/run-2026 prepare
uv run python -m email_workshop.persona_pipeline --workshop-root . \
  --root artifacts/persona-qwen2.5-7b --model-profile qwen2.5-7b \
  --clients priya-raman-support daniel-okafor-cfo noah-williams-assistant
```

Stop the writer vLLM if it is running (§1), then train. Adapters are trained one at a time. The
pipeline reuses only complete adapters with matching lineage.

```bash
uv run python -m email_workshop.persona_pipeline --workshop-root . \
  --root artifacts/persona-qwen2.5-7b --model-profile qwen2.5-7b \
  --clients priya-raman-support daniel-okafor-cfo noah-williams-assistant --run
cat artifacts/persona-qwen2.5-7b/persona_pipeline/status.json
```

On a 64 GB Spark, use `--root artifacts/persona-qwen2.5-3b --model-profile qwen2.5-3b`. All
adapters served together must share **one** base model and revision.

Adapters land in `artifacts/persona-qwen2.5-7b/persona_adapters/<adapter>/`. The adapter names
(`priya-raman`, `daniel-okafor`, `noah-williams`) come from the persona registry. They must match
`writer_adapter` in `config/persona_permissions.json`.

---

## 6. Writer: vLLM Multi-LoRA (:8001) and writer service (:8100)

Serve the shared base model with all three adapters. Use the same vLLM image as the controller.
Some images already set `vllm serve` as the entrypoint; drop the leading `vllm serve` from the
command if yours does.

```bash
# start in workshops/email-multilora
RUN=artifacts/persona-qwen2.5-7b
REV=$(python3 -c "import json;print(json.load(open('$RUN/persona_adapters/priya-raman/manifest.json'))['config']['model_revision'])")
docker run -d --name pd-writer --gpus all --ipc=host -p 127.0.0.1:8001:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  -v "$PWD/$RUN":/adapters:ro \
  <vllm-image-from-the-recipe> \
  vllm serve Qwen/Qwen2.5-7B-Instruct --revision "$REV" \
    --host 0.0.0.0 --port 8000 \
    --gpu-memory-utilization 0.20 --max-model-len 4096 \
    --enable-lora --max-loras 3 --max-lora-rank 8 \
    --lora-modules priya-raman=/adapters/persona_adapters/priya-raman \
                   daniel-okafor=/adapters/persona_adapters/daniel-okafor \
                   noah-williams=/adapters/persona_adapters/noah-williams
curl -sS http://127.0.0.1:8001/v1/models | python3 -m json.tool   # base + 3 adapter ids
```

Here `--host 0.0.0.0` is the address **inside** the container. It is reachable only because
`-p 127.0.0.1:8001:8000` publishes the port to the host's loopback interface.

The revision comes from the adapter's `manifest.json`. vLLM must load the exact base revision
the adapters were trained on. `email_workshop.persona.persona_vllm_command` builds the same
`--lora-modules` list, in `python -m` form on port 8000.

Start the writer service. It verifies the adapter against the registry and returns lineage
(`base_model`, `base_revision`, `adapter_revision`) with every draft:

```bash
# start in workshops/email-multilora
EMAIL_PERSONA_RUN=artifacts/persona-qwen2.5-7b \
uv run --extra training --with fastapi --with uvicorn \
  python ../personal-agent-multilora/scripts/writer_service.py \
  --backend vllm --vllm-url http://127.0.0.1:8001 --port 8100
curl -sS http://127.0.0.1:8100/health
```

Switch the personas to the HTTP writer and re-run a job:

```bash
cd workshops/personal-agent-multilora
uv run python scripts/setup_hermes.py --apply --writer http --writer-url http://127.0.0.1:8100 \
  --model <served-model-id> --base-url http://127.0.0.1:8000/v1
uv run personadesk --profile pd-priya run --fixture priya-002
uv run personadesk --profile pd-priya show <job-id>   # draft now carries adapter lineage
```

**Learning check:** run the same fixture for each persona, with the template writer and then with
the adapter writer. Facts come from tools and policy checks, so they should match. Tone and
phrasing should differ by persona.

---

## 7. Classification: K0 baseline and real CLM

### K0 lexical baseline (CPU, minutes)

```bash
cd workshops/email-multilora
uv run --with scikit-learn python ../personal-agent-multilora/scripts/classification_k0.py \
  --data-root artifacts/run-2026
```

This writes `workshops/personal-agent-multilora/artifacts/classification/c10_lexical.json` and
`k0_c10_report.json`. The test split stays sealed. Point a persona at the baseline:

```bash
hermes -p pd-priya config set plugins.entries.personadesk.settings.classifier.backend lexical
hermes -p pd-priya config set plugins.entries.personadesk.settings.classifier.lexical_artifact \
  artifacts/classification/c10_lexical.json
```

### Real CLM backend (GPU)

```bash
# 1. encoder: Qwen3-8B pooling on :8090 (same vLLM image; loopback only)
docker run -d --name clm-encoder --gpus all --ipc=host -p 127.0.0.1:8090:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface <vllm-image-from-the-recipe> \
  vllm serve Qwen/Qwen3-8B --served-model-name qwen3-8b --runner pooling \
    --enable-prefix-caching --max-model-len 2048 --gpu-memory-utilization 0.15 \
    --host 0.0.0.0 --port 8000
```

```bash
# 2. CLM API on :8700 (start in external/CLM; downloads a 75 MB head on first run)
cd external/CLM
uv venv && uv pip install -e .
uv run clm-serve --host 127.0.0.1 --port 8700 --emb-url http://127.0.0.1:8090/v1/embeddings
```

```bash
curl -sS http://127.0.0.1:8700/health   # must NOT contain "mock": true; models must list clm-latest
```

Enable it per persona:

```bash
hermes -p pd-priya config set plugins.entries.personadesk.settings.classifier.backend clm
hermes -p pd-priya config set plugins.entries.personadesk.settings.classifier.clm_url http://127.0.0.1:8700
```

The plugin checks `/health` before sending any message content. It refuses a mock server, a
missing embedder, or a missing model unless `allow_mock` is set, which is meant for wiring labs
only. Results from a mock server are flagged `real_backend: false`.

**Learning check:** compare K0 and CLM on the same validation messages. Look at C10 multi-label
F1, at the labels each flags for review (`review_margin`), and at how often C6 abstains
(`abstain_below`). These are inputs to a reviewed release, never automatic actions.

---

## 8. Self-improvement: feedback and releases

Everything here is human-gated. Nothing self-modifies.

1. **Collect.** Export the consented, reviewed drafts from the development split:

   ```bash
   cd workshops/personal-agent-multilora
   uv run personadesk --profile pd-priya export-feedback   # -> artifacts/feedback/priya-raman-support.jsonl
   ```

2. **Retrain.** Train an adapter candidate (§5) into a **new** `--root`, for example
   `artifacts/persona-qwen2.5-7b-r2`. Keep the old run.
3. **Evaluate.** Evaluate the candidate on the frozen validation split. Write a report with
   `"passed": true|false` under the workshop's `artifacts/`.
4. **Create a candidate release.** Copy the adapter's `manifest.json` into the workshop, so its
   digest is pinned, and create an immutable candidate. Release creation is deliberately not a
   CLI or tool command:

   ```bash
   cd workshops/personal-agent-multilora
   mkdir -p artifacts/release-inputs
   cp ../email-multilora/artifacts/persona-qwen2.5-7b-r2/persona_adapters/priya-raman/manifest.json \
      artifacts/release-inputs/priya-raman-r2-manifest.json
   uv run python -c "
   from pathlib import Path; from hermes_plugin import releases
   m = releases.create_candidate(Path('.'), client_id='priya-raman-support', created_by='trainer',
       components={'adapter': {'path': 'artifacts/release-inputs/priya-raman-r2-manifest.json'}},
       evaluation_report='artifacts/release-inputs/priya-raman-r2-eval.json',
       base={'model': 'Qwen/Qwen2.5-7B-Instruct'}, policy_version='2026-10-25.1')
   print(m['release_id'])"
   ```

5. **Promote or roll back.** The approver is your OS user. Promotion is refused if:
   - the approver is the candidate's `created_by`;
   - the evaluation failed;
   - the report changed after the candidate was created;
   - any component digest no longer matches.

   ```bash
   uv run personadesk --profile pd-priya release list
   uv run personadesk --profile pd-priya release promote <release-id>
   uv run personadesk --profile pd-priya release active
   uv run personadesk --profile pd-priya release rollback
   ```

6. **Switch the writer.** Point the writer at the promoted run (`EMAIL_PERSONA_RUN`, plus
   `--lora-modules` on :8001). To roll back, restore the previous run.

---

## 9. Phase checklist

| Phase | Done when |
|-------|-----------|
| E0 fake worker | `uv run pytest` passes; fake-worker job reaches `awaiting_review` |
| E1 real controller | `pd-priya` job via Hermes produces a draft with tool evidence |
| E2 isolation | cross-persona and out-of-grant requests are denied and logged |
| E3 adapters | three adapters trained; `/v1/models` on :8001 lists them |
| E4 adapter writer | drafts carry `base_revision` and `adapter_revision` |
| K0 / CLM | lexical report written; CLM `/health` non-mock; classifier tool returns labels or abstains |
| Releases | promote and rollback work; self-approval is rejected |

---

## 10. Remote access from a laptop

```bash
ssh -N -L 8000:127.0.0.1:8000 -L 8100:127.0.0.1:8100 -L 8700:127.0.0.1:8700 <user>@<spark-host>
```

Then `http://127.0.0.1:8700/` opens the CLM playground on the laptop. Do not expose these ports
on the LAN: none of them authenticate.

---

## 11. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| vLLM fails at start with insufficient memory | Another process holds its fraction; lower `--gpu-memory-utilization`, or stop a process (§1). Start the largest process first. |
| Controller answers in text, no `tool_calls` | Wrong or missing `--tool-call-parser` / `--enable-auto-tool-choice`; re-check the recipe. |
| Job ends `failed` with `no_draft` | The controller never called `pd_draft_reply`; raise `max_turns` in `config/persona_permissions.json`, or use a stronger controller. |
| Writer `503 Adapter not verified` | `EMAIL_PERSONA_RUN` points at the wrong run root, or adapter lineage does not match. |
| Writer `403` | Adapter name differs from the persona registry. |
| `/v1/models` on :8001 lacks an adapter | `--lora-modules` path wrong inside the container; check the `-v` mount. |
| Classifier `unavailable` | CLM `/health` shows mock, missing embedder, or missing `clm-latest`. |
| `torch.cuda.is_available()` is `False` | aarch64 wheel without CUDA; use the NGC PyTorch container (§2). |
| `hermes plugins doctor` cannot find config | Set `PERSONADESK_ROOT` to the workshop directory. |

Stop everything:

```bash
docker rm -f pd-writer clm-encoder <controller-container>
```
