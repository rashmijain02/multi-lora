# Configurable three-task experiments

These pipelines share preparation, validation, baselines, causal-LM LoRA training,
adapter reload, and validation/test evaluation. They deliberately do **not** share
one accuracy score or turn emotion/generation datasets into empathy annotations.

| Experiment profile | Task and supervision | Local verification subset |
|---|---|---|
| `configs\experiments\fictional-local.json` | Fictional 0/1/2 empathy mechanisms with rationales and verbatim evidence | 20 train / 8 validation / 8 test |
| `configs\experiments\goemotions-local.json` | GoEmotions multi-label emotion classification over its 28 labels | 64 train / 16 validation / 16 test |
| `configs\experiments\empatheticdialogues-local.json` | EmpatheticDialogues listener-response generation from preceding dialogue | 64 train / 16 validation / 16 test |

The local profiles use pinned Qwen2.5-0.5B-Instruct, BF16, batch 1, gradient
accumulation 2, checkpointing, and 20 optimizer steps. They verify the engineering
on a 10 GB RTX 3080; they are not recommended final training budgets or quality
benchmarks. The fictional test cohort has already informed teaching observations.
See [measured evidence](VALIDATION.md) and [larger-model planning](LARGE_MODEL_EXPERIMENT.md).

## Setup and dataset acquisition

Commands start at the repository root, then explicitly enter the workshop:

```powershell
Set-Location workshops\leadership-evidence-lab
uv sync --extra dev --extra training --extra data
uv run pytest -q
uv run ruff check empathy_lab tests
```

All following commands start in `workshops\leadership-evidence-lab`. Select **one**
experiment profile. For example:

```powershell
$config = "configs\experiments\goemotions-local.json"
$run = "my-goemotions-01"
uv run python -m empathy_lab experiment prepare --config $config --download
uv run python -m empathy_lab experiment validate --config $config --tokens
```

Repeat with the other profiles to learn their separate tasks. `--download` explicitly
authorizes acquisition of the pinned public data. It is unnecessary for fictional
fixtures. Without it, public preparation uses existing local source files or fails
with an acquisition instruction. Validation, training, and evaluation never download
datasets implicitly. Model/tokenizer loading can still download the approved pinned
model if it is not cached; use an offline Hugging Face environment after caching if
network-free execution is required.

Dataset links, licenses, and manual acquisition instructions are in
[the dataset section](LARGE_MODEL_EXPERIMENT.md#where-to-obtain-each-dataset).
GoEmotions uses its simplified Parquet files at an immutable HF commit.
EmpatheticDialogues uses the official archive and a pinned SHA-256, with CC BY-NC 4.0
restrictions. No upstream training scripts or remote model code are executed.

Raw public files go under ignored `data\external\`; prepared snapshots go under
ignored `data\prepared\`. Original `data\fictional_support.jsonl` remains tracked
and fictional-only. Preparing public data does not alter it or bypass its loader.

## Train, validate, and freeze before testing

Continue in the workshop directory using the same `$config` and `$run`:

```powershell
uv run python -m empathy_lab experiment baseline --config $config --run $run --split validation
uv run python -m empathy_lab experiment evaluate --config $config --run $run --split validation
uv run python -m empathy_lab experiment train --config $config --run $run
uv run python -m empathy_lab experiment evaluate --config $config --run $run --split validation --adapted
```

Check each exit status before continuing. Use training and validation results to make
modeling choices. Freeze the model, data, prompt, and budgets before the final test:

```powershell
uv run python -m empathy_lab experiment baseline --config $config --run $run --split test
uv run python -m empathy_lab experiment evaluate --config $config --run $run --split test
uv run python -m empathy_lab experiment evaluate --config $config --run $run --split test --adapted
```

Training opens only prepared train and validation files, never test content.
Evaluation reloads the saved adapter and checks its model/task/data provenance.
Existing adapters and reports are not overwritten: use a distinct `--run` for a new
attempt. Artifacts, checkpoints, and aggregate JSON reports live in
`artifacts\experiments\<run>\`. Do not commit weights or public source text.

Generation is greedy and the raw continuation must satisfy the task contract.
There is no hidden JSON repair, retry, or silent target/context truncation. An
overlength example raises an error: curate it explicitly or increase the recorded
token budget and repeat validation. `max_length` bounds prompt plus target during
training and prompt plus maximum new tokens during evaluation.

## What data validation does

Preparation validates complete source data before selecting a verification subset.
It writes a manifest with source revision/checksums, licenses, source/admitted/selected
counts, split policy, per-split checksums, and a prepared-data fingerprint.
GoEmotions shard completeness and its Parquet label-index metadata are checked before
conversion. Subsequent commands reject modified prepared files.

Scenario/comment/conversation groups cannot cross splits. Identical normalized
inputs across splits retain the earlier train, then validation, then test ownership;
later duplicates are removed and counted **before** seeded subset selection.
Consequently these are audited variants of official splits, not untouched leaderboard
submissions. Within-split repeated inputs are retained; this is not semantic or
near-duplicate detection. GoEmotions simplified exposes comment IDs, not complete
thread/author groups: its audit establishes comment/input separation, not thread-
or person-disjoint evaluation.

EmpatheticDialogues is reconstructed by conversation and utterance index, not by CSV
row position or speaker identity. Each even-indexed listener utterance becomes a
target; only preceding turns become its prompt. Conversations with missing/duplicate
indices are excluded and counted rather than assigned invented context. Extra
metadata/candidate columns are ignored and counted; autobiographical `prompt`,
speaker identifiers, and self-evaluation metadata are not model inputs. Shared
preceding turns within a conversation are not independent human observations.

## Task-specific metrics and privacy

| Task | Baseline | Model evaluation |
|---|---|---|
| Fictional empathy | Train-only TF-IDF and logistic heads; constant-class fallback | Strict schema/evidence coverage, valid-only per-mechanism macro-F1, all-example correct rates |
| GoEmotions | Train-only TF-IDF and one binary logistic head per label; constant-class fallback; threshold 0.5 with argmax fallback | Fixed 28-label micro/macro-F1 and exact match; malformed generations count as empty predictions, not dropped examples |
| EmpatheticDialogues | Most frequent training response, a deliberately weak lexical control | Response coverage, single-reference token overlap/exact match, response-only token NLL/perplexity |

Every model evaluation also records response-only teacher-forced loss. Token overlap
and likelihood are **not empathy, helpfulness, or clinical-quality measurements**.
Generation quality needs separately designed human evaluation. The lexical classifier
does not generate rationales, so its score coverage is not evidence-generation coverage.

New experiment reports contain aggregates, not source text, example identifiers,
references, or generated responses. Prepared data and adapters remain sensitive
local artifacts. The older fictional-only `infer --report` API still retains raw
fictional generations; it is not the public-data reporting path.
Model train/evaluation reports also record Python/package versions, CUDA runtime,
device type, and GPU name without developer checkout paths.

## Change modeling choices through configuration

An experiment JSON selects the task, source, subset sizes/seed, reusable model profile,
and optional model overrides. Model-profile paths resolve relative to the experiment
file, while the fictional dataset path resolves relative to the workshop source.
Prepared data and artifact paths are source-resolved, not dependent on the terminal's
working directory.

| Field | How to experiment |
|---|---|
| `name` / CLI `--run` | Give a new run a distinct name; keep earlier results intact |
| `model_profile` | Select a flat profile such as `../qwen-local.json` or `../qwen-large.json`; pin model/tokenizer to the same 40-character commit |
| `model_overrides` | Override batch/accumulation, learning rate, steps, sequence/generation budgets, rank/alpha/dropout/target modules, evaluation cadence, warmup, precision, seed, or gradient checkpointing |
| `chat_template_kwargs` inside model overrides | Pass supported native `enable_thinking` or `reasoning_effort` options explicitly; a low reasoning effort is not necessarily a non-thinking mode |
| `limits` | Positive per-split example caps for smoke runs; use `null` to admit the complete audited split |
| `seed` | Reproduce subset selection; the model profile's `seed` separately controls model/training randomness |
| `dataset.revision` | Immutable HF dataset commit for GoEmotions; official archive SHA-256 for EmpatheticDialogues |

Copy a local experiment JSON into `configs\experiments\`, change its model-profile
reference and budget, then repeat prepare/validate/baseline/evaluate/train with a new
run name. If data settings are unchanged, the same prepared snapshot is reused across
models; changing a model alone does not resample data. Baselines can be reused
conceptually, but their saved report is associated with its run.

Conventional Transformers causal-LM checkpoints with compatible chat templates and
PEFT targets need configuration, not a new task pipeline. This does **not** promise
arbitrary architecture compatibility: multimodal processors, Harmony final-channel
extraction, custom remote code, quantized training, and distributed sharding still need
reviewed integrations. `device: auto` does not pool GPU memory. Full-dataset runs must
pass token-budget validation and a resource pilot; the short local recipe does not
become a meaningful full-corpus training budget merely by setting limits to `null`.

## Final status and advanced learner next steps

**Status as of 2026-11-10: implementation and local engineering verification complete.**
All three tasks completed preparation, token validation, baseline/unadapted/adapted
validation and test evaluation, and saved-adapter reload. Verification passed
31 workshop tests, 33 Hub tests, lint/format checks, and full execution of all four
leadership notebooks with model/training/test opt-ins enabled. Notebook 04 passed
independently for each of the three tasks; outputs were not saved in notebook sources.
Three primary 20-step Qwen 0.5B training calls on the 10 GB RTX 3080 totaled about
35 seconds; the complete sequential verification took about six minutes.

**Modeling is not finished.** Adapted fictional output was invalid on 6/8 test
examples; GoEmotions adapted macro-F1 was only 0.0417 on 16 examples and lower than
the unadapted arm. EmpatheticDialogues likelihood/overlap improvements do not establish
better support quality. Full-data training, larger-model qualification, and independent
human quality evaluation remain learner work. No leadership-assessment claim is supported.
See [the full measurements and protocol](VALIDATION.md#configurable-three-task-verification-2026-11-10).

### Recommended order: change one factor at a time

| Priority | What to try | What to hold fixed and measure | Work needed |
|---|---|---|---|
| 1. Reproduce | Run one supplied local profile with a fresh run name, then the other tasks | Confirm data fingerprints, adapter reload, coverage, and baseline/base/adapted comparisons; exact floating-point scores can vary by hardware | Existing commands and configuration |
| 2. Learn a data curve | Start with GoEmotions: 500, then 2,000, then 5,000 training examples and a fixed 512-example validation subset | Keep model, data-selection seed, prompt, and decoding fixed. Compare macro/micro-F1, exact match, valid coverage, training exposure, and cost | Change `limits` and training/evaluation budgets; repeat preparation and token checks |
| 3. Improve the exact empathy task | Author a larger fictional cohort, beginning with about 500 training exchanges and a separately annotated validation cohort | Keep scenario families disjoint. Check strict JSON/evidence validity separately from mechanism accuracy and human-reviewed rationale support | New original data and independent annotation; existing fictional schema/pipeline |
| 4. Study response generation | Expand EmpatheticDialogues to 2,000, then 10,000 training response examples after a resource pilot | Keep conversation ownership and evaluation cohorts fixed. Report token likelihood/overlap alongside a blinded human comparison of context grounding, responsiveness, and unsupported assumptions | Existing generation pipeline; a separate human-evaluation protocol |
| 5. Scale the model | With one admitted dataset frozen, compare the local model with one larger conventional instruction model | Change model size before architecture or data size. Compare each base model with its own adapter; record precision, memory, full generation cost, and label/response metrics | New pinned model profile and measured compatibility/resource pilot |
| 6. Check robustness | Repeat finalist configurations with model/training seeds 17, 42, and 73 | Keep the dataset-selection seed and cohorts fixed. Freeze decisions on validation before final test evaluation; report seed spread and failures | Configuration changes; cluster-aware uncertainty analysis is a separate extension |

**Best first advanced experiment:** the GoEmotions learning curve, still using the
verified small model. It has existing human labels, a larger available training pool,
and objective task-specific metrics, without first needing a new dataset or runtime.
Do not infer empathy from its emotion labels or prefer micro-F1 alone when macro-F1
reveals weak performance across the fixed label set.

For each data tier, derive `max_steps` from actual admitted training size and a
declared exposure budget rather than keeping the 20-step smoke recipe. On one device:

`steps per epoch ~= ceil(training examples / (batch_size * gradient_accumulation_steps))`

Begin with one epoch; consider additional exposure using validation only. Set
`eval_steps` deliberately so larger validation sets do not dominate every few
training steps. Before longer runs, measure a representative training/validation/save
pilot, including long examples, and agree a wall-time/memory budget. More examples
or a model that loads successfully do not guarantee that training fits.

For model scaling, the prepared Qwen 7B and Nemotron Nano 8B profiles are continuity
options on suitable hardware, not locally qualified results. The
[larger-model proposal](LARGE_MODEL_EXPERIMENT.md#3-models-and-training-ladder) covers
7B/14B/32B planning and independent families. Keep the 0.5B control and try only one
larger candidate initially; newer hybrid/MoE/multimodal models may still require
engineering rather than a profile change.

### Evaluation boundary and extensions

The published smoke-test cohorts have already been inspected; do not call them
sealed or use their failures to tune a new claim. Continue modeling on train and
validation. For a new research claim, reserve an unexamined evaluation cohort,
document which examples were previously inspected, and use independent annotations
where the task requires them. The pipeline does not automatically create a fresh,
independently annotated research benchmark.

Constrained decoding, classifier-head alternatives, rare-label threshold calibration,
auxiliary-then-task adaptation, semantic deduplication, cluster-bootstrap confidence
intervals, QLoRA, and distributed training are **not implemented**. Treat each as a
separately reviewed extension, not an undocumented configuration key or a prerequisite
for the first learning curve. Never weaken output validation, invent missing public
empathy labels, or repair test outputs silently to improve a score.

Finish an advanced experiment with one short comparison: the hypothesis, pinned
model/data/configuration, baseline and adapted validation results, frozen final
evaluation, resource cost, uncertainty, and whether the added data or model size was
worthwhile. Publish reviewed aggregates only; keep public source text, raw generations,
and potentially memorizing adapters local unless reuse and release have been approved.
