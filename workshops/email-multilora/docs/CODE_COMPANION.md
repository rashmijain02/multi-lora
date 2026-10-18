# Email Multi-LoRA Workshop Code Companion

This guide is a source-code tour for a new reader. It explains how the workshop turns a
public multi-label email dataset into a lexical router, four LoRA adapters, resumable
evaluations, optional local serving, and separate Azure hosting workflows.

Read this after the main [workshop guide](../README.md). Use
[LOCAL_SETUP.md](LOCAL_SETUP.md) for executable setup commands.

## 1. What the workshop builds

The core local workflow is:

```text
Pinned email dataset
        |
        v
Validate, deduplicate and split
        |
        +--------------------+
        |                    |
        v                    v
TF-IDF domain router     One frozen language model
                             |
                             +-- generalist LoRA
                             +-- operations LoRA
                             +-- finance LoRA
                             +-- travel LoRA
                                      |
                                      v
                          Compare four strategies
```

The task is **multi-label classification**. One email may have several labels:

```json
["Finance & Bills", "Travel & Bookings"]
```

The task is not mutually exclusive multiclass classification, email reply generation,
workflow automation, invoice extraction, or action execution.

## 2. Repository map

```text
workshops/email-multilora/
├── email_workshop/
│   ├── data.py              # taxonomy, prompts, download, validation and splits
│   ├── routing.py           # TF-IDF domain router and threshold selection
│   ├── training.py          # LoRA training, manifests and local PEFT inference
│   ├── evaluation.py        # strategies, strict output parsing and metrics
│   ├── serving.py           # optional local vLLM command/client
│   ├── cli.py               # individual prepare/router/train/evaluate commands
│   ├── pipeline.py          # staged, resumable end-to-end local workflow
│   ├── cloud_api.py         # protected Container Apps classification API
│   ├── foundry.py           # managed Foundry chat-completions client
│   └── foundry_*.py         # separate Foundry provisioning/probe/smoke helpers
├── notebooks/               # guided workshop interfaces over the same package
├── scripts/                 # environment setup and guarded deployment helpers
├── tests/                   # synthetic and tiny-model contract tests
├── infra/                   # Container Apps and Foundry Bicep
├── docs/                    # setup, deployment and agent runbooks
└── artifacts/               # ignored local data, adapters and predictions
```

The package is the source of truth. Notebooks call package functions rather than carrying
separate implementations.

## 3. Start with `data.py`

Open [data.py](../email_workshop/data.py).

### 3.1 Taxonomy

`LABELS` declares the ten valid labels:

```text
Business
Customer Support
Events & Invitations
Finance & Bills
Job Application
Newsletters
Personal
Promotions
Reminders
Travel & Bookings
```

`DOMAINS` groups them into three specialist domains:

```python
operations = eight non-finance/non-travel labels
finance = ("Finance & Bills",)
travel = ("Travel & Bookings",)
```

`ADAPTERS` adds the all-label `generalist`:

```python
ADAPTERS = ("generalist", "operations", "finance", "travel")
```

`allowed_labels(adapter)` is the central vocabulary guard:

- `generalist` and `base` receive all labels.
- Each specialist receives only its domain labels.
- Unknown adapter names are rejected.

Training prompts, output validation, evaluation and serving all use this same function.

### 3.2 Dataset lineage

The public dataset ID and immutable revision are constants. Preparation downloads one
pinned JSON file and verifies its content hash. It does not execute a remote dataset script.

The manifest records:

- Dataset ID and revision.
- Source SHA-256.
- Seed.
- Deduplication policy.
- Split sizes and hashes.
- Per-label counts.

This makes an experiment auditable and prevents accidental comparisons across changed data.

### 3.3 Row validation and duplicate handling

`validate_rows()` checks:

- Input is a non-empty JSON array.
- Subject and body are non-empty strings.
- Labels are a non-empty list of unique known strings.
- Labels are placed in canonical taxonomy order.

An email ID is the SHA-256 fingerprint of normalized subject and body text.

Duplicate policy:

```text
Same text + same labels       -> keep one row
Same text + conflicting labels -> quarantine the entire text group
```

Conflicting text is excluded rather than arbitrarily choosing one label set.

### 3.4 Split construction

`prepare()` creates iterative multi-label train/validation/test partitions:

```text
Train:      70%
Validation: 15%
Test:       15%
```

Iterative stratification preserves minority-label representation better than a simple
random split.

The test split is written during preparation but remains sealed during normal development.

### 3.5 Prompt construction

`messages(subject, body, labels)` creates the chat prompt.

The system instruction:

- Defines the allowed labels.
- Requires a JSON array.
- Prohibits explanations and unknown labels.

The user message contains only subject and body. Ground-truth labels never appear in an
inference prompt.

## 4. The lexical router in `routing.py`

Open [routing.py](../email_workshop/routing.py).

The router is deliberately simple and independent of the LLM:

```text
Subject + body
    |
    v
TF-IDF features
    |
    v
One-vs-rest logistic regression
    |
    v
Operations / finance / travel scores
```

### 4.1 Why a separate router?

Calling all three specialists guarantees coverage but costs three LLM calls per email.
Routing tries to call only likely domains.

Example:

```text
"Your hotel booking is confirmed"
    -> travel

"Flight invoice ready"
    -> finance + travel
```

### 4.2 Leakage controls

`fit_router()`:

1. Fits vocabulary and classifiers on **train only**.
2. Evaluates candidate thresholds on **validation only**.
3. Selects the highest threshold meeting the configured aggregate domain-recall target.
4. Saves the selected threshold and every threshold trial.

The router sees only email text. It never uses ground-truth labels to choose adapters at
inference time.

### 4.3 Routing limits

A missed domain creates a coverage error before the LLM runs:

```text
Finance label required
        |
Router does not select finance
        |
Finance adapter never sees the email
        |
Finance label cannot be recovered
```

The evaluation therefore reports:

- Routing domain recall.
- Routing label-coverage ceiling.
- Mean model calls.
- Model classification metrics.

These must not be collapsed into one number.

## 5. LoRA training in `training.py`

Open [training.py](../email_workshop/training.py).

This module was previously named `modeling.py`. New code should import
`email_workshop.training`.

### 5.1 `TrainConfig`

`TrainConfig` records every relevant training input:

```python
model_profile
model_id
model_revision
target_modules
seed
max_length
rank
epochs
learning_rate
batch_size
gradient_accumulation
max_steps
sample_limit
device
```

The model profile and revision are required for reproducibility. Built-in and custom choices
are resolved by [model_profiles.py](../email_workshop/model_profiles.py). A custom choice must
supply an immutable revision and explicit LoRA target modules.

### 5.2 Prompt-length control

`prompt_ids()`:

1. Tokenizes subject and body separately.
2. Limits the subject first.
3. Applies the model's own chat template.
4. Shortens the body until the prompt fits the available budget.
5. Preserves room for the complete JSON target.

The target is never silently truncated.

### 5.3 Completion-only training

`training_example()` returns:

```python
{
    "input_ids": prompt + completion,
    "attention_mask": ...,
    "labels": [-100 for prompt tokens] + completion
}
```

`-100` tells PyTorch loss calculation to ignore prompt tokens. Training loss is applied
only to:

- The expected JSON array.
- The EOS token.

The model learns the answer format and labels rather than reproducing the prompt.

### 5.4 Specialist targets

Every specialist trains on every training email.

Example:

```text
Email labels:
["Finance & Bills", "Travel & Bookings"]

generalist target -> ["Finance & Bills", "Travel & Bookings"]
operations target -> []
finance target    -> ["Finance & Bills"]
travel target     -> ["Travel & Bookings"]
```

Off-domain `[]` examples teach specialists when not to emit labels.

Positive-only training would make a one-label specialist prone to returning its label for
nearly every email.

### 5.5 Attaching LoRA

`train_adapter()` loads the pinned tokenizer and base model, then calls PEFT
`get_peft_model()` with:

```text
Rank:          8
Alpha:         16
Dropout:       0.05
Target modules: selected profile (for both current built-ins: q_proj, v_proj)
Task:          causal language modeling
```

The original attention weights remain frozen. LoRA adds small trainable low-rank matrices:

```text
Adapted matrix = frozen W + scale * B * A
```

Only `A` and `B` are optimized.

For the local Nemotron run:

```text
Total parameters:     8,033,669,120
Trainable parameters: 3,407,872
Trainable fraction:   0.0424%
```

### 5.6 Independent adapters

The four adapters are not trained in one continuous model:

```text
Load fresh base -> train generalist -> save -> release
Load fresh base -> train operations -> save -> release
Load fresh base -> train finance -> save -> release
Load fresh base -> train travel -> save -> release
```

This prevents one specialist from inheriting another specialist's updates.

### 5.7 Checkpoint selection

Training evaluates after each epoch and keeps the checkpoint with the lowest validation loss.

The final adapter may therefore come from epoch 1 even when two epochs were executed.

### 5.8 Adapter manifest

Each adapter receives a `manifest.json` containing:

- Adapter name.
- Exact base ID/revision.
- Full `TrainConfig`.
- Dataset fingerprint.
- Training-row ID fingerprint.
- Allowed labels.
- Smoke/workshop purpose.
- Trainable and total parameters.
- Training metrics/history.
- Best checkpoint.
- Package versions.
- File SHA-256 hashes.

`verify_adapters()` checks:

1. All four adapters exist.
2. Adapter identity matches directory name.
3. Dataset fingerprint matches the run.
4. Saved-file hashes still match.
5. Every adapter used the same base/training configuration.

## 6. Local adapter inference

`LocalBackend` in [training.py](../email_workshop/training.py) loads:

1. One base model.
2. The generalist adapter.
3. The other three adapters into the same PEFT wrapper.

The base weights are stored in memory once.

For an adapted call:

```python
self.model.set_adapter("finance")
self.model.generate(...)
```

For the base comparison:

```python
with self.model.disable_adapter():
    self.model.generate(...)
```

This backend switches adapters sequentially. It does not prove that different adapters can
share one GPU batch.

## 7. Evaluation in `evaluation.py`

Open [evaluation.py](../email_workshop/evaluation.py).

### 7.1 Strict output parsing

`parse_labels()` accepts only a JSON array of unique allowed strings:

```json
["Business", "Reminders"]
```

It rejects:

```text
Markdown fences
Explanatory prose
Unknown labels
Duplicate labels
Non-string values
Out-of-domain specialist labels
```

Invalid output is not silently repaired.

### 7.2 Four strategies

#### Base

```text
Email -> base model with adapters disabled
```

This measures what adapter training added.

#### Generalist

```text
Email -> generalist adapter -> all ten labels available
```

One model call per email.

#### All specialists

```text
Email -> operations
      -> finance
      -> travel
      -> union valid labels
```

Three model calls per email.

#### Routed specialists

```text
Email -> router -> selected specialist(s) -> union valid labels
```

Usually close to one call per email, but labels can be missed when routing skips the
required domain.

### 7.3 Resumable prediction files

Before generation, `evaluate()` fingerprints:

- Backend identity.
- Adapter manifests.
- Router metadata.
- Strategy.
- Split.
- Row sequence.
- Prompt contracts.

If a prediction file exists, it must have the same fingerprint and contain an exact prefix
of the expected row IDs. The evaluator then resumes from the next row.

This is why the earlier Windows file-replacement interruption resumed safely without
retraining or recomputing completed rows.

### 7.4 Metrics

`score()` reports:

- Exact label-set match.
- Valid exact match.
- Micro-F1.
- Macro-F1.
- Hamming loss.
- Invalid-output rate.
- Per-label precision/recall/F1/support.
- Calls per email.
- Sequential p50/p95 latency.

For specialist strategies it also adds routing coverage measurements.

## 8. Command interfaces

### 8.1 Individual CLI

Open [cli.py](../email_workshop/cli.py).

It provides focused commands:

```powershell
python -m email_workshop.cli --artifacts artifacts/example prepare
python -m email_workshop.cli --artifacts artifacts/example router
python -m email_workshop.cli --artifacts artifacts/example train --device cuda
python -m email_workshop.cli --artifacts artifacts/example evaluate --device cuda
```

Training accepts a built-in profile:

```powershell
--model-profile nemotron-nano-8b
```

For an unlisted compatible base, use `--model-profile custom` with `--model-id`,
`--model-revision` and `--target-modules`.

Use individual commands when teaching or investigating one stage.

### 8.2 Staged pipeline

Open [pipeline.py](../email_workshop/pipeline.py).

The staged pipeline runs:

```text
prepare -> router -> train -> evaluate
```

Without `--run`, it prints a plan and performs no downloads, training, evaluation or cloud calls.

Profiles:

```text
smoke -> limited rows/steps/evaluation
full  -> full train and validation partitions
```

The pipeline:

- Reuses complete compatible stages.
- Rejects incomplete adapter directories.
- Rejects changed seed/router/training configuration.
- Writes stage status after each completed phase.
- Excludes the test split unless `--include-test` is explicitly supplied.

## 9. Notebooks

The notebooks are guided interfaces:

| Notebook | Purpose |
|---|---|
| `01_email_data_and_routing.ipynb` | Dataset audit, split integrity, lexical baseline and router |
| `02_train_email_adapters.ipynb` | Training contract, tokenization and optional adapter training |
| `03_compare_and_serve.ipynb` | Strategy comparison and optional local vLLM exercise |

Costly operations use explicit booleans and ship disabled where appropriate.

Notebook outputs should be cleared before committing because they can contain machine-specific
paths, email content or misleading stale results.

## 10. Optional vLLM serving

Open [serving.py](../email_workshop/serving.py).

The vLLM lab is Linux/WSL2-only and separate from the Windows PEFT training environment.

`vllm_command()`:

- Verifies all adapter manifests.
- Builds static `--lora-modules` registrations.
- Uses relative Linux paths.
- Enables at most four LoRAs.
- Does not enable runtime adapter uploading.

`VllmBackend` permits loopback endpoints only. This prevents the workshop from accidentally
sending email text to an arbitrary remote vLLM server.

The concurrent demo proves concurrent successful calls, not same-batch GPU scheduling.

## 11. Azure code is a separate path

The local workshop and Azure hosting should not be confused.

### Container Apps API

[cloud_api.py](../email_workshop/cloud_api.py) exposes:

```text
GET  /healthz
POST /classify
```

Classification requires a workshop Bearer token. Input length and schema are validated.
API docs are disabled.

### Foundry client

[foundry.py](../email_workshop/foundry.py) sends the email prompt to an existing compatible
Foundry chat-completions endpoint.

This is managed-model prompting:

```json
{
  "backend": "foundry-managed",
  "trained_adapter": false
}
```

It does not load the local Qwen or Nemotron LoRA adapters.

### Provisioning

Foundry and Container Apps provisioning have separate Bicep templates, approval gates,
configuration files, costs and runbooks.

Start with:

- [AZURE_DEPLOYMENT.md](AZURE_DEPLOYMENT.md)
- [FOUNDRY_MODEL_DEPLOYMENT.md](FOUNDRY_MODEL_DEPLOYMENT.md)

## 12. Tests

The test suite uses:

- Synthetic rows.
- Temporary directories.
- Tiny random Qwen models.
- HTTP test doubles.
- Synthetic Azure configuration.

Important test files:

| File | Coverage |
|---|---|
| `test_pipeline.py` | Dataset, router, evaluation and notebook contracts |
| `test_training.py` | Completion masks, real optimizer steps, save/load/switch |
| `test_staged_pipeline.py` | Plan mode, stage execution and resumability |
| `test_paths.py` | Repository portability and relative paths |
| `test_foundry*.py` | Managed inference and guarded deployment behavior |

Tests do not prove production model quality or Azure availability.

## 13. How to read a completed run

An artifact run looks like:

```text
artifacts/<run>/
├── data/
│   ├── manifest.json
│   ├── train.json
│   ├── validation.json
│   └── test.json
├── router/
│   ├── metadata.json
│   └── validation_metrics.json
├── adapters/
│   ├── generalist/
│   ├── operations/
│   ├── finance/
│   └── travel/
├── evaluation/
│   ├── peft-validation-base.json
│   ├── peft-validation-generalist.json
│   ├── peft-validation-all-specialists.json
│   ├── peft-validation-routed.json
│   └── corresponding metrics files
└── pipeline/
    ├── status.json
    └── result.json
```

Suggested reading order:

1. `data/manifest.json`
2. `router/metadata.json`
3. Each adapter `manifest.json`
4. Strategy metrics files
5. Row-level predictions for error analysis
6. The dated run report

Do not commit artifact directories. They contain email text, model weights, predictions and
machine-specific execution records.

## 14. Current experiment interpretation

The local Nemotron validation run found:

| Strategy | Micro-F1 | Exact match | Calls/email |
|---|---:|---:|---:|
| Base | 0.1340 | 5.13% | 1.000 |
| Generalist LoRA | **0.8465** | **73.72%** | 1.000 |
| All specialists | 0.8142 | 69.23% | 3.000 |
| Routed specialists | 0.8020 | 67.95% | 1.032 |

This demonstrates:

- LoRA successfully taught the strict task and JSON contract.
- Larger zero-shot models are not automatically better at constrained classification.
- The generalist was the strongest design in this validation run.
- Routing reduced specialist calls but did not beat the generalist.
- A specialist architecture may still be justified by ownership, policy or independent
  retraining requirements.

These are validation findings. The test split remains sealed.

## 15. Safe extension checklist

When changing the workshop:

1. Pin model and dataset revisions.
2. Use a fresh artifact root.
3. Keep the test split sealed during development.
4. Preserve completion-only masking.
5. Preserve off-domain negative examples.
6. Never route from ground-truth labels.
7. Keep invalid output visible.
8. Verify adapter/data/config fingerprints before resume.
9. Record package versions and hashes.
10. Run the smallest relevant tests, then the full available suite.
11. Clear notebook outputs before commit.
12. Keep paths repository-relative.
13. Never send real email text to remote services without explicit approval.

## 16. Recommended next reading

1. [README.md](../README.md) for the workshop narrative.
2. [LOCAL_SETUP.md](LOCAL_SETUP.md) for local execution.
3. [data.py](../email_workshop/data.py) for lineage and task definition.
4. [training.py](../email_workshop/training.py) for LoRA mechanics.
5. [evaluation.py](../email_workshop/evaluation.py) for strategy semantics.
6. A completed dated report under the ignored artifact run directory.
