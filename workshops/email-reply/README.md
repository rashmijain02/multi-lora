# Workshop 7: Email reply QLoRA SFT and locally judged GRPO

Does supervised fine-tuning on real email conversations improve reply drafting over a prompted
instruction model, and how do we refine a supervised adapter when historical replies contain
unseen context? This workshop runs a local, reproducible pipeline over prepared
conversation-to-reply JSONL datasets (defaulting to `input\enron\reply-conversations.jsonl`):

- **Shared foundation (`util\`):** dataset validation and inferred thread-grouped splits (10%
  final holdout, 10% validation), newest-first prompt budgeting, configurable model profiles,
  local-only telemetry (`metrics.jsonl`), and headless Matplotlib visualizations.
- **Supervised stage (`sft\`):** compare the unadapted prompt baseline against 4-bit QLoRA SFT
  (`Qwen/Qwen3-4B-Instruct-2507` default) on identical held-out conversations with periodic
  step-based validation.
- **Checkpoint-initialized RL stage (`grpo\`):** continue training from a saved SFT adapter with
  grouped rollouts, a frozen local rubric judge (`grpo\judge.py`), KL regularization against a
  frozen `"sft_ref"` copy of the SFT checkpoint, periodic validation selection, and 3-stage
  (`baseline` vs. `sft` vs. `grpo`) comparison plots.

Read [PLAN.md](PLAN.md) first for the split design, supervision masking, hardware scaling,
monitoring artifacts, and evaluation caveats.

## Quick start

Start at the repository root and switch into this workshop folder:

```powershell
Set-Location workshops\email-reply
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Prepared training inputs live under `input\enron\` (or a custom directory passed via `--input-dir`).
Generated runs, split manifests, adapters, `metrics.jsonl` logs, headless PNG plots, and optional
private sample outputs live under `output\` (or a custom directory passed via `--output-dir`).
Inputs are eligible for version control; review them carefully before publishing and never commit
private mail. Generated outputs remain git-ignored and restricted to the local user.

## Input directory structure and schema

Both `sft` and `grpo` read a single prepared JSONL file named `reply-conversations.jsonl` inside
the selected `--input-dir` (default `input\enron\`):

```text
workshops\email-reply\
└── input\
    ├── enron\
    │   ├── reply-conversations.jsonl   # Required by SFT and GRPO
    │   ├── replies.jsonl               # Auxiliary legacy benchmark artifact (unused by SFT/GRPO)
    │   └── candidate\                  # Auxiliary legacy candidate records (unused by SFT/GRPO)
    └── <custom-dataset>\
        └── reply-conversations.jsonl   # Prepared via tools\prepare_input.py
```

Each line in `reply-conversations.jsonl` must be a JSON object with two non-empty `str` fields:

| Field | Type | Contract |
| --- | --- | --- |
| `conversation` | `string` | Visible thread context **preceding** the target reply, rendered newest-message-first (`-----Original Message-----` header blocks). Must not contain later messages or verbatim copies of the target reply. |
| `reply` | `string` | Authored target reply body only (without trailing quoted thread history). |

Synthetic JSONL record example:

```json
{"conversation": "-----Original Message-----\nFrom: Alice <alice@example.test>\nSent: 2024-10-01T09:00:00Z\nTo: Bob <bob@example.test>\nSubject: Q3 forecast\n\nCan you confirm the Q3 forecast deadline?", "reply": "Friday at 4 PM Central."}
```

> **Privacy warning:** Although `input\` is not git-ignored so synthetic or public datasets can be
> versioned intentionally, converting private mail into an `input\<dataset>\` folder does **not**
> authorize committing or publishing it. Keep private mail outside version control or inspect `git
> status` before committing.

## Converting mail threads to `reply-conversations.jsonl`

Use `tools\prepare_input.py` (`python -m tools.prepare_input` from `workshops\email-reply`) to
convert mail exports into a fresh dataset directory without modifying source files or overwriting an
existing `reply-conversations.jsonl`.

- **Exit codes & aggregate diagnostics:** stdout prints aggregate JSON counts (`accepted`,
  `rejected`, `rejection_reasons`) with **no** message text. Exit `0` means all candidate records
  were accepted, `2` means a valid subset was written and exclusions were counted, and `1` means
  conversion failed without publishing an empty dataset.
- **Target selection & linkage:** message-based formats require explicit reply links (`In-Reply-To`
  / `References`) or explicit thread/chronology boundaries—never subject-only matching. Select
  targets via `--target-message-id`, `--target-sender`, `--target-flag-field`, embedded target
  markers, or `--target-selection latest` on unambiguous threads.

Run any of the synthetic examples below from `workshops\email-reply` (using a temporary workspace
`$tmp` so your checkout stays clean), then point `--input-dir` at the prepared destination:

```powershell
$py = '.\.venv\Scripts\python.exe'
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) "email-reply-prep-demo"
Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $tmp | Out-Null

# 1. .eml (file or directory of MIME messages; attachments are excluded automatically)
New-Item -ItemType Directory -Path "$tmp\eml_src" | Out-Null
Set-Content -Path "$tmp\eml_src\01.eml" -Encoding utf8 -Value @"
Message-ID: <m1@example.test>
From: Alice <alice@example.test>
To: Bob <bob@example.test>
Date: Mon, 01 Oct 2024 09:00:00 +0000
Subject: Q3 forecast
Content-Type: text/plain; charset="utf-8"

Can you confirm the Q3 forecast deadline?
"@
Set-Content -Path "$tmp\eml_src\02.eml" -Encoding utf8 -Value @"
Message-ID: <m2@example.test>
In-Reply-To: <m1@example.test>
From: Bob <bob@example.test>
To: Alice <alice@example.test>
Date: Mon, 01 Oct 2024 09:30:00 +0000
Subject: Re: Q3 forecast
Content-Type: text/plain; charset="utf-8"

Friday at 4 PM Central.
"@
& $py -m tools.prepare_input --format eml --source "$tmp\eml_src" --output-dir "$tmp\out_eml" --target-message-id "<m2@example.test>"

# 2. .mbox (standard mailbox export; later forwards are excluded from earlier targets)
& $py -c "import mailbox, pathlib; p = pathlib.Path(r'$tmp'); b = mailbox.mbox(p / 'demo.mbox'); b.add((p / 'eml_src/01.eml').read_bytes().removeprefix(b'\xef\xbb\xbf')); b.add((p / 'eml_src/02.eml').read_bytes().removeprefix(b'\xef\xbb\xbf')); b.flush(); b.close()"
& $py -m tools.prepare_input --format mbox --source "$tmp\demo.mbox" --output-dir "$tmp\out_mbox" --target-sender "bob@example.test"

# 3. Structured JSON (canonical threads/messages or custom --field-map)
Set-Content -Path "$tmp\threads.json" -Encoding utf8 -Value '{"threads":[{"thread_id":"t1","target_message_id":"m2","messages":[{"message_id":"m1","sender":"alice@example.test","timestamp":"2024-10-01T09:00:00Z","subject":"Window","body":"Is Saturday 02:00 UTC approved?"},{"message_id":"m2","in_reply_to":"m1","sender":"bob@example.test","timestamp":"2024-10-01T09:15:00Z","subject":"Re: Window","body":"Yes, Saturday 02:00 UTC is approved."}]}]}'
& $py -m tools.prepare_input --format json --source "$tmp\threads.json" --output-dir "$tmp\out_json"

# 4. Quoted or delimited plain text (--text-contract delimited or quoted-reply)
Set-Content -Path "$tmp\thread.txt" -Encoding utf8 -Value @"
=== MESSAGE ===
Message-ID: <t1@example.test>
From: Dana <dana@example.test>
Sent: 2024-10-03T10:00:00Z
Subject: Clause 4

Did legal sign off on clause 4?
=== MESSAGE ===
Message-ID: <t2@example.test>
In-Reply-To: <t1@example.test>
From: Eli <eli@example.test>
Sent: 2024-10-03T10:20:00Z
Subject: Re: Clause 4
Target: true

Legal approved clause 4 without changes.
"@
& $py -m tools.prepare_input --format text --text-contract delimited --source "$tmp\thread.txt" --output-dir "$tmp\out_text"

# 5. CSV or JSONL (mapped conversation/reply columns or message-per-row exports)
Set-Content -Path "$tmp\pairs.csv" -Encoding utf8 -Value "prompt_thread,target_reply`n`"-----Original Message-----`nFrom: Pat`nSubject: Invoice`n`nDid invoice 884 clear?`",`"Invoice 884 cleared this morning.`""
& $py -m tools.prepare_input --format csv --mode paired --field-map conversation=prompt_thread --field-map reply=target_reply --source "$tmp\pairs.csv" --output-dir "$tmp\out_csv"
```

Select any prepared destination directory during training via `--input-dir "$tmp\out_json"` (and
optionally relocate generated runs via `--output-dir "$tmp\runs"`).

## Prompt baseline vs. QLoRA SFT (12 GB GPU)

On Windows with an RTX 50-series (Blackwell) or other CUDA GPU, create an isolated Python 3.12
environment from `workshops\email-reply` using `uv`:

```powershell
uv venv .venv --python 3.12
$py = '.\.venv\Scripts\python.exe'
uv pip install --python $py --index-url https://pypi.org/simple --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match "torch==2.10.0+cu128" -r requirements.txt
& $py -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"
```

See the [Unsloth Blackwell installation guide](https://unsloth.ai/docs/blog/fine-tuning-llms-with-blackwell-rtx-50-series-and-unsloth)
if your driver or toolkit differs. Run `sft\experiment.py` as a module from `workshops\email-reply`
(or directly from the repository root, `workshops\email-reply`, or `workshops\email-reply\sft`):

```powershell
# Fast 1-step GPU workflow check
.\.venv\Scripts\python.exe -m sft.experiment --smoke

# Full prompt baseline + SFT + paired holdout comparison with periodic validation
.\.venv\Scripts\python.exe -m sft.experiment --eval-steps 50

# Write side-by-side held-out conversations, drafts, and references into the private run folder
.\.venv\Scripts\python.exe -m sft.experiment --smoke --show-private
```

Each SFT run freezes `<output-dir>\sft\split-42.json`, persists the prompt-only base-model holdout
evaluation in `<output-dir>\baseline\<run-id>\summary.json` (unless `--baseline-run` reuses an
existing compatible baseline run), and writes SFT artifacts inside `<output-dir>\sft\<run-id>\`.

## Checkpoint-initialized QLoRA GRPO (`grpo\experiment.py`)

After training an SFT run (for example `output\sft\<sft-run-id>`), run `grpo\experiment.py` from
`workshops\email-reply` to optimize the SFT adapter against the frozen local judge while keeping an
immutable `"sft_ref"` copy of the SFT adapter on the quantized base model for KL regularization:

```powershell
# Bounded GPU smoke check from a saved SFT run (uses default local Qwen3-4B CPU judge)
.\.venv\Scripts\python.exe -m grpo.experiment `
  --sft-run output\sft\<sft-run-id> `
  --smoke

# Full GRPO training with periodic validation and reused baseline comparison
.\.venv\Scripts\python.exe -m grpo.experiment `
  --sft-run output\sft\<sft-run-id> `
  --baseline-run output\baseline\<baseline-run-id> `
  --group-size 4 --temperature 0.8 --beta 0.04 --eval-steps 25
```

- **Lineage & immutability:** GRPO verifies that the SFT adapter's base model, optional revision,
  and LoRA target modules match `--model-id`/`--revision`/`--target-modules` (automatically
  inheriting a saved SFT revision when `--revision` is omitted), verifies `split-42.json` against
  the active dataset SHA-256, never modifies the source SFT checkpoint, and exports a separate
  portable PEFT adapter plus `adapter\grpo-lineage.json`.
- **Live GRPO telemetry & plots:** `metrics.jsonl` flushes per-step total and per-dimension rewards,
  group reward std, tied-group rate, invalid completion counts, completion word length, KL
  divergence vs. `"sft_ref"`, rollout/judge latency splits, CUDA memory, and periodic `--eval-steps`
  validation metrics; `training_metrics.png` and 4-panel `comparison.png` (`BASELINE` vs. `SFT` vs.
  `GRPO`) render headlessly without private message text.

## Output layout, monitoring, and visualizations

Beneath `--output-dir` (default `output\`), each stage writes into its own immutable,
local-user-restricted run tree:

```text
<output-dir>\
├── baseline\
│   └── <run-id>\
│       ├── summary.json                  # Aggregate holdout metrics + comparison_identity (no email text)
│       └── heldout-sample-outputs.txt    # Written only when --show-private is passed
├── sft\
│   ├── split-42.json                     # Frozen thread-grouped train/validation/holdout manifest
│   └── <run-id>\
│       ├── summary.json                  # Aggregate metrics, baseline_run link, comparison_identity
│       ├── metrics.jsonl                 # Append-only step & periodic --eval-steps validation telemetry
│       ├── loss.png                      # Train/validation reply-token loss curve
│       ├── training_metrics.png          # 4-panel loss, LR, grad-norm, and memory/step-time chart
│       ├── comparison.png                # Cross-stage holdout chart (baseline vs. SFT)
│       ├── adapter\                      # Best validation PEFT adapter + experiment-base.json
│       └── heldout-sample-outputs.txt    # Paired baseline/SFT samples (only with --show-private)
└── grpo\
    └── <run-id>\
        ├── summary.json                  # Aggregate metrics, lineage, baseline/SFT links, judge config
        ├── metrics.jsonl                 # Append-only step rewards, rubric means, KL, and eval checks
        ├── training_metrics.png          # 4-panel reward, rubric dimensions, KL/grad, length/ties chart
        ├── comparison.png                # Cross-stage holdout chart (baseline vs. SFT vs. GRPO)
        ├── adapter\                      # Best validation GRPO PEFT adapter + grpo-lineage.json
        └── heldout-sample-outputs.txt    # Paired 3-stage samples (only with --show-private)
```

- **Periodic validation (`--eval-steps`):** evaluates validation loss (SFT) or validation judge
  reward (GRPO) every `N` optimizer steps plus a guaranteed final validation pass, marking the
  selected best checkpoint in `metrics.jsonl` and `training_metrics.png`.
- **Standalone or reused baseline (`--baseline-only`, `--baseline-run`):** pass `--baseline-only`
  to record an unadapted baseline run on its own, or `--baseline-run <path>` to reuse a saved
  baseline run (even across different `--output-dir` roots) after verifying matching dataset/split
  hashes, base model/revision, prompt budget, and deterministic decoding.
- **Privacy gate (`--show-private`):** `summary.json`, `metrics.jsonl`, stderr logs, and PNG plots
  never contain email or draft text; raw conversations, model drafts, and archived replies are
  written to `heldout-sample-outputs.txt` only when `--show-private` is explicitly supplied.

## Configuring directories and models

Override input/output storage and base-model profiles directly from the CLI without editing code
(`--revision` and `--judge-revision` are optional and accept any valid branch, tag, or commit hash
when you want to pin a specific snapshot):

```powershell
.\.venv\Scripts\python.exe -m sft.experiment `
  --input-dir input\enron `
  --output-dir output `
  --model-id Qwen/Qwen3-4B-Instruct-2507 `
  --target-modules q_proj k_proj v_proj o_proj `
  --end-token "<|im_end|>"
```

Relative `--input-dir` and `--output-dir` overrides resolve from the caller's working directory;
omitting them selects the source-relative workshop defaults regardless of working directory. Any
custom `--output-dir` inside the repository checkout must already be covered by `.gitignore`.

## Frozen local model judge (`grpo\judge.py`)

GRPO rewards candidate completions with an **independent, frozen local causal LM** rather than
string overlap against archived replies (which can contain offline facts absent from the visible
thread):

- **Local-only model identity:** `--judge-model-id` defaults to `Qwen/Qwen3-4B-Instruct-2507`, and
  `--judge-revision` is optional (`None` by default, or pass a branch, tag, or commit hash). Remote
  HTTP/API endpoints (`https://...`, `openai:...`, etc.) are rejected—there is **no hosted judge
  fallback**.
- **CPU default & local device override:** `--judge-device` defaults to `cpu` so the second model
  does not compete with 4-bit QLoRA policy rollouts on a 12 GB GPU. Pass `--judge-device cuda` (and
  optionally `--judge-four-bit`) on larger GPUs or when sequential VRAM headroom permits.
- **Versioned rubric (`email-reply-rubric-v1`):** scores `relevance`, `grounding`, and
  `uncertainty` as integers in `0..4` (`reward = (relevance + grounding + uncertainty) / 12.0`)
  under deterministic decoding (`do_sample=False`). Only the visible conversation shown to the
  policy and the candidate draft (wrapped in `<untrusted_...>` tags) are passed—never the archived
  reply or truncated unseen context.
- **Fail-closed validation & limitations:** malformed JSON, out-of-range/non-integer scores, prompt
  budget overflows, and runtime errors abort explicitly instead of silently substituting `0.0`.
  Model-judge scores remain heuristic model judgments susceptible to judge bias rather than verified
  ground truth; inspect per-dimension trajectories in `training_metrics.png` and paired samples.

## Layout

| Path | Role |
| --- | --- |
| `tools/prepare_input.py` | Standalone `.eml`, `.mbox`, JSON, plain/quoted-text, and CSV/JSONL dataset converter |
| `util/paths.py` | Source-relative path discovery, `.gitignore` checks, and local-user ACL restrictions |
| `util/data.py` | Two-field dataset validation, deduplication, and inferred thread-grouped frozen splits |
| `util/prompts.py` | `ModelProfile`, `Hardware`, newest-first prompt budgeting, and reply-only supervision masks |
| `util/models.py` | Base-model/adapter identity checks and Unsloth 4-bit QLoRA loading |
| `util/monitoring.py` | Privacy-safe `metrics.jsonl` logger, progress callbacks, and headless PNG diagnostics |
| `util/evaluation.py` | Paired held-out generation, reference-token loss, comparison identity checks, and samples |
| `sft/trainer.py` | Periodic-validation QLoRA SFT trainer and portable PEFT adapter export |
| `sft/experiment.py` | CLI and library runner for baseline + QLoRA SFT evaluation |
| `grpo/judge.py` | Frozen local causal-LM judge (`email-reply-rubric-v1`) |
| `grpo/trainer.py` | Checkpoint-initialized QLoRA GRPO loop with frozen `"sft_ref"` KL and telemetry |
| `grpo/experiment.py` | CLI and library runner for SFT-to-GRPO optimization and 3-stage comparison |
| `tests/` | Focused CPU unit tests for paths, conversion, splits, prompts, judge, monitoring, SFT, and GRPO |
| `input/enron/` | Default prepared conversation/reply dataset (`reply-conversations.jsonl`) |
| `output/` | Local git-ignored stage runs, split manifests, adapters, telemetry, plots, and samples |
