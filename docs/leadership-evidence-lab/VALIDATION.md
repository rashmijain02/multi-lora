# Initialization evidence

Observed on 2026-11-09. These are measurements on original fictional fixtures, **not**
a reproduction of Sharma et al. (2020) or an evaluation of psychological validity.
The historical initialization below is followed by a separate 2026-11-10
three-task engineering verification; their protocols and results are not interchangeable.

## Environment and protocol

- Windows host, RTX 3080 with 10,240 MiB VRAM, approximately 63 GiB system RAM.
- Python 3.12; torch 2.10.0+cu128; transformers 4.57.6; peft 0.18.1.
- [Local configuration](../../workshops/leadership-evidence-lab/configs/qwen-local.json): Qwen2.5-0.5B-Instruct at
  `7ae557604adf67be50417f59c2c2f167def9a775`, FP16, seed 42, rank 8,
  30 optimizer steps, batch 1, gradient accumulation 4, learning rate 0.0002.
- 36 fictional records: 20 train, eight validation, eight test, with disjoint scenario
  families. Fixture SHA-256:
  `53b97b144df01039d4989adbbdf5bccf364b854592fb19a3bb4434b05b1c6c93`.
- Lexical features fit on training only. LoRA uses completion-only loss; validation is
  separate. The frozen default configuration was evaluated on test without test-driven
  hyperparameter changes.
- Local artifacts are under `artifacts/local-initialization`, ignored by Git.

## Observed results

Each mechanism has levels 0, 1, 2. Macro-F1 uses these fixed classes and only valid model
responses. The invalid count must be read alongside every score. All model outputs are
greedy, with the configured 192-token generation cap; no format-repair retries are used.

| Model / split | Invalid / total | Emotional reactions macro-F1 | Interpretations macro-F1 | Explorations macro-F1 |
|---|---:|---:|---:|---:|
| Lexical / validation | 0 / 8 | 0.7111 | 0.8586 | 0.7111 |
| Lexical / test | 0 / 8 | 0.5630 | 0.2222 | 0.5630 |
| Qwen unadapted / validation | 7 / 8 | 0.3333 | 0.3333 | 0.3333 |
| Qwen LoRA / validation | 5 / 8 | 0.6667 | 0.6667 | 0.6667 |
| Qwen unadapted / test | 8 / 8 | Not defined | Not defined | Not defined |
| Qwen LoRA / test | 5 / 8 | 0.1667 | 0.1667 | 0.1667 |

The local 30-step run completed, but **did not produce a reliable structured classifier**.
The three valid adapted test predictions are not sufficient to support any generalization
claim. In particular, the validation F1 increase is not evidence that LoRA outperforms the
lexical baseline or the original research model.

Measured LoRA training call elapsed time was 27.30 seconds; Trainer reported 19.66 seconds
for its training loop. Peak CUDA tensor allocation was approximately 2.33 GiB, and peak
PyTorch reserved memory approximately 3.43 GiB. These are process-specific allocator
measurements, not total device usage or promises about larger model memory.

## Verification

- Package tests cover dataset/split validation, rationale evidence, prediction parsing,
  invalid-output accounting, train-only baseline behavior, and response-only masking.
- All three notebooks were executed with expensive model cells disabled; their baseline
  and data-understanding paths were checked without persisting outputs.
- Actual Qwen validation inference, LoRA training, and frozen test comparison were run
  separately with the same package APIs.
- Workshop Hub manifest validation passes.

## Larger-machine experiments

[Qwen 7B](../../workshops/leadership-evidence-lab/configs/qwen-large.json) and
[Nemotron 8B](../../workshops/leadership-evidence-lab/configs/nemotron-large.json) have pinned configurations only. Neither has
been run here. The README documents hardware planning targets and model-license terms.
Use the same fixtures, splits, prompt, and evaluation accounting when comparing them.

Next experimental changes must be selected on training/validation, not on this test
set's failures. For a meaningful new claim, collect more independently annotated fictional
scenarios and reserve a fresh test cohort. Investigate structured-output reliability
separately from empathy-label correctness; invalid outputs must never be scored as zero.

## Configurable three-task verification: 2026-11-10

The [shared workflow](EXPERIMENTS.md) was run end-to-end on the same RTX 3080
(10,240 MiB VRAM): source preparation, full-source data checks, token audits,
train-only baselines, unadapted validation, LoRA training, adapter reload, adapted
validation, and explicit frozen baseline/base/adapted test evaluations.

Environment: Python 3.12.15, torch 2.10.0+cu128, Transformers 4.57.6, PEFT 0.18.1,
PyArrow 23.0.1. All three profiles used Qwen2.5-0.5B-Instruct at the same immutable
revision recorded above, BF16, seed 42, rank 8/alpha 16/dropout 0.05, batch 1,
gradient accumulation 2, gradient checkpointing, learning rate 0.0002, and
20 optimizer steps. Sequence budget was 1,024; generation caps were 256 for fictional
JSON and 128 for the public tasks. No text was silently truncated or outputs repaired.

### Data checks

| Task | Full admitted train / validation / test examples | Selected verification counts | Data findings |
|---|---|---|---|
| Fictional empathy | 20 / 8 / 8 | 20 / 8 / 8 | Original fixtures unchanged; scenario-disjoint |
| GoEmotions | 43,410 / 5,377 / 5,379 | 64 / 16 / 16 | Original counts 43,410 / 5,426 / 5,427; removed 49 validation and 48 test duplicate inputs |
| EmpatheticDialogues | 36,594 / 5,696 / 5,235 listener-response examples | 64 / 16 / 16 | Excluded 42 / 3 / 3 incomplete conversations, then removed 11 validation and four test duplicate inputs |

EmpatheticDialogues source utterance counts were 76,673 / 12,030 / 10,943.
Incomplete conversations accounted for 101 / 11 / 8 utterances; no missing context
was fabricated. Extra metadata columns were counted but excluded from model inputs.
All retained dialogue targets use preceding context only and preserve conversation
ownership. This is a derived, audited dataset, not the untouched official benchmark.
GoEmotions simplified cannot establish thread/author-disjointness from comment IDs.

The source revision/archive checksum is pinned in each experiment JSON. Prepared
manifests record source/admitted/selected counts, sampling seed, per-file checksums,
and data fingerprints. Raw and prepared public text remain in ignored local storage.

### Training resources

| Profile | Steps | Training-call seconds | Peak CUDA tensor allocation |
|---|---:|---:|---:|
| `fictional-local` | 20 | 11.17 | 1.61 GiB |
| `goemotions-local` | 20 | 12.64 | 1.24 GiB |
| `empatheticdialogues-local` | 20 | 11.31 | 1.20 GiB |

The three primary training calls totaled 35.13 seconds. The complete sequential
verification, including separate process/model loading and all evaluations, took
379.9 seconds. Allocator peaks are process-specific, not total device usage or
larger-model capacity guarantees. A final one-step GoEmotions regression run also
verified automatic environment metadata and adapter reload using the final code.

### Held-out smoke results, not quality claims

Fictional unadapted test output was invalid on **8/8** examples; adapted output
remained invalid on **6/8**. Each adapted mechanism had valid-only macro-F1 0.3333
on the two valid predictions and all-example correct rate 0.1250. The lexical
baseline's score-only macro-F1 was 1.0000 / 0.6000 / 1.0000 for emotional reactions,
interpretations, and explorations. It does not generate rationales or evidence.
This shared baseline vectorizes the task prompt rather than the old conversation-only
representation, so it is not the historical baseline protocol above.

| GoEmotions test arm | Valid / total | Micro-F1 | Fixed-28-label macro-F1 | Exact match |
|---|---:|---:|---:|---:|
| Lexical baseline | 16 / 16 | 0.2286 | 0.0232 | 0.2500 |
| Unadapted | 15 / 16 | 0.2353 | 0.0898 | 0.1875 |
| LoRA | 16 / 16 | 0.2857 | 0.0417 | 0.2500 |

Adaptation improved JSON coverage but **reduced macro-F1 versus the unadapted model**.
The 16 examples and many unsupported labels cannot establish general performance.

| EmpatheticDialogues test arm | Non-empty / total | Mean token F1 | Response-token perplexity |
|---|---:|---:|---:|
| Most-frequent-training-response baseline | 16 / 16 | 0.0881 | Not applicable |
| Unadapted | 16 / 16 | 0.0903 | 59.83 |
| LoRA | 16 / 16 | 0.1429 | 17.76 |

All three generation arms had zero exact matches. Lexical overlap, likelihood, and
non-empty output do not establish empathy, helpfulness, safety, or clinical validity.
These small, single-seed, 20-step runs verify code and data flow only; no large model
was trained and no conclusion about leadership or larger datasets follows.

### Persistent evidence and checks

Aggregate reports and saved adapters are under ignored
`artifacts\experiments\fictional-local\`, `goemotions-local\`, and
`empatheticdialogues-local\` in the workshop. Each run has `training.json`,
baseline/base/adapted validation and test JSON, plus its adapter. Public-data reports
contain no source text, identifiers, reference responses, or generated responses.

Final verification passed: **31 workshop tests**, **33 Workshop Hub tests**, Ruff
(including notebook sources), Python formatting checks, Hub manifest validation, and all
three token audits. Existing train-only, fictional-only, and strict evidence contracts
remain covered.

### Full notebook execution

All four leadership notebooks were executed in memory without saving outputs, using
the pinned local data and model caches. Model inference, training, and explicit test
evaluation opt-ins were enabled for this check; passing only the default disabled
branches was not treated as sufficient.

| Notebook | Executed path | Result |
|---|---|---|
| `01_data_understanding.ipynb` | Data/schema/split exploration and baseline inputs | Passed |
| `02_manual_training.ipynb` | Validation baseline and model inference; local Qwen LoRA training | Passed, 59.94 seconds |
| `03_evaluation.ipynb` | Reload notebook 02's adapter; frozen baseline/base/adapted test comparison | Passed, 74.89 seconds |
| `04_configurable_tasks.ipynb` | Full configured workflow for fictional empathy, GoEmotions, and EmpatheticDialogues independently | All three passed |

The first enabled notebook run caught an absolute-output-path mismatch in notebook 02;
notebook 03 consequently lacked its adapter. Notebook 02 now selects the workshop
working directory temporarily and passes a validated relative destination, without
weakening the trainer's path guard. Both notebooks then passed with a fresh shared run
name. Regression tests exercise the notebook-produced destination from the repository,
workshop, and notebook directories.

These are execution checks, not additional quality claims. Notebook source files
still contain no saved outputs or execution counts. The three changed email-workshop
notebooks contain documentation-link changes only; their executable cells and saved
execution state are unchanged from the release base.
