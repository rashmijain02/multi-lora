# Leadership Evidence Lab: configurable modeling workshop

Documentation: `docs/leadership-evidence-lab/`. Code and workshop-relative commands: `workshops/leadership-evidence-lab/`.

Start with **fictional empathy-expression classification**, inspired by the three
communication mechanisms in [Sharma et al.'s research](https://github.com/behavioral-data/Empathy-Mental-Health).
No Reddit or TalkLife text is bundled in the fixtures. All fixture labels are author-created
teaching judgments, not validated psychological measurements. Optional, explicit public-data
preparation now supports GoEmotions emotion classification and EmpatheticDialogues response
generation as separate tasks, not additional empathy ground truth.

This is **not a reproduction of the published study**: data, models, and experimental
design differ. We compare a lexical baseline, an instruction model, and a supervised LoRA
on the same fictional examples. Person-level traits, leadership mapping, independent
human annotation studies, and Hermes optimization remain later phases of the
[proposal](PROPOSAL.md).

## Start with the shared experiment workflow

See [three-task experiments](EXPERIMENTS.md) for dataset acquisition, provenance/split
validation, train-only baselines, unadapted evaluation, response-only LoRA training,
adapter reload, and frozen test evaluation through the same configurable commands.
Local profiles use Qwen 0.5B and small subsets for engineering verification; learner
profiles can change model, data size, and training budgets without rewriting the task.

| Task | Profile in the workshop | Output |
|---|---|---|
| Original fictional empathy | `configs\experiments\fictional-local.json` | Mechanism scores, rationales, and exact evidence |
| GoEmotions | `configs\experiments\goemotions-local.json` | Multi-label emotion JSON, not empathy scores |
| EmpatheticDialogues | `configs\experiments\empatheticdialogues-local.json` | Listener response from preceding dialogue |

Raw/public prepared data and adapters are ignored. New experiment reports are
aggregate-only. Public data acquisition is opt-in and EmpatheticDialogues remains
noncommercial under CC BY-NC 4.0.

## Hardware and model choices

Hardware observed on the development host on 2026-11-09: RTX 3080, 10,240 MiB VRAM
(9,066 MiB free at inspection), approximately 63 GiB system RAM. Available memory varies.

| Profile | Model | Execution plan |
|---|---|---|
| [Local Qwen](../../workshops/leadership-evidence-lab/configs/qwen-local.json) | Qwen2.5-0.5B-Instruct, Apache-2.0 | FP16 inference and small LoRA on the local 10 GB GPU; no quantization dependencies |
| [Larger Qwen](../../workshops/leadership-evidence-lab/configs/qwen-large.json) | Qwen2.5-7B-Instruct, Apache-2.0 | BF16 inference on >=24 GB GPU; allow >=48 GB for this unquantized training recipe and measure actual peak usage |
| [Larger Nemotron](../../workshops/leadership-evidence-lab/configs/nemotron-large.json) | Llama-3.1-Nemotron-Nano-8B-v1 | BF16 inference on >=24 GB GPU; >=48 GB training planning target, preferably 80 GB; not run on the 10 GB host |

These are conservative planning targets, not measured large-model memory requirements.
Use Linux for the larger-machine experiments. Models are pinned to immutable Hugging Face
revisions. Nemotron is selected for its standard Transformers Llama architecture rather
than a newer hybrid architecture requiring a different runtime. Its NVIDIA Open Model
License and additional Llama terms are **not MIT**; review the
[official card](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Nano-8B-v1).
Reasoning is disabled following that card. Do not silently substitute models or revisions.

## Setup

Start in the repository root, then:

```powershell
Set-Location workshops\leadership-evidence-lab
uv sync --extra dev --extra training --extra data
uv run python -m ipykernel install --sys-prefix --name empathy-lab --display-name "Empathy Lab"
uv run pytest -q
uv run ruff check empathy_lab tests
```

For the original fictional-only command-line replay, from the workshop directory:

```powershell
uv run python -m empathy_lab validate
uv run python -m empathy_lab baseline --split validation
uv run python -m empathy_lab infer --config configs\qwen-local.json --split validation --report artifacts\qwen-local\base-validation.json
uv run python -m empathy_lab train --config configs\qwen-local.json --output artifacts\qwen-local\adapter
uv run python -m empathy_lab infer --config configs\qwen-local.json --split validation --adapter artifacts\qwen-local\adapter --report artifacts\qwen-local\adapted-validation.json
```

After freezing validation choices, change `--split validation` to `--split test` for a
final comparison. On a larger machine, substitute the Qwen-large or Nemotron-large config
and distinct output directories. `--help` documents each command. Never overwrite another
model's adapter and then treat it as the original run.

Select the Empathy Lab kernel in VS Code. For CUDA, install the matching official PyTorch
CUDA wheel if the resolved build is CPU-only; confirm `torch.cuda.is_available()` before
training. Dependencies and model downloads are separate from fixture preparation.
The current lockfile selects the official CUDA 12.8 PyTorch index for the training extra.
See [initial measured evidence](VALIDATION.md): the local Qwen run completed but produced
many invalid JSON responses and is not yet a reliable classifier.

## Notebooks: manual inspection before automation

1. [01: Data understanding](../../workshops/leadership-evidence-lab/notebooks/01_data_understanding.ipynb): inspect fictional
   conversations, 0/1/2 labels, rationale spans, distributions, and scenario-family splits.
2. [02: Manual training and testing](../../workshops/leadership-evidence-lab/notebooks/02_manual_training.ipynb): fit a train-only
   lexical baseline, select a configurable model, run validation inference, and train LoRA
   with response-only loss. GPU work is explicitly opt-in.
3. [03: Evaluation](../../workshops/leadership-evidence-lab/notebooks/03_evaluation.ipynb): evaluate frozen choices once on test;
   examine per-mechanism confusion, macro-F1, balanced accuracy, invalid outputs, and errors.
4. [04: Configurable tasks](../../workshops/leadership-evidence-lab/notebooks/04_configurable_tasks.ipynb):
   select one of the three tasks; explicitly opt into public downloads, model execution,
   training, and final test evaluation using the shared experiment API.

Notebook paths resolve from either the repository root, workshop directory, or notebooks
directory. Outputs are cleared in source control. Inspect fictional text locally; do not
replace it with personal conversations in committed notebooks.

## Experimental discipline

- Keep all conversations from one scenario family in one split.
- Fit vocabulary, classifier, and adapter only on training examples; use validation
  for manual choices. Do not tune against the small teaching test set.
- Report each mechanism separately: emotional reactions, interpretations, explorations.
  Emotion classification and expressed empathy are not equivalent.
- Malformed model responses are invalid predictions, not zero empathy. Report invalid
  rate and valid-only scores together; disclose abstentions in the denominator.
- Fictional author labels and small sample counts cannot establish real-world validity,
  fairness, stability of personality, or clinical utility.
- Publish recipes and reviewed aggregate reports by default, not downloaded model weights.
  See the repository [publication policy](../../README.md#personal-learning-publication-policy).

## Larger-machine experiment

For a staged learner proposal covering DGX Spark/shared memory, machines with up to
128 GB GPU memory, 7B/14B/32B comparisons, larger datasets, and implementation gates,
see [larger-model experiments](LARGE_MODEL_EXPERIMENT.md). Public-data task pipelines
are implemented for GoEmotions and EmpatheticDialogues; QLoRA, distributed training,
and arbitrary architecture integrations remain extensions.

Copy the repository (without local caches/artifacts) to the approved machine, create the
environment there, and select `configs/qwen-large.json` or `configs/nemotron-large.json`
in notebooks 02 and 03. Keep the data and split unchanged. Match training steps or report
the differing budgets explicitly; compare unadapted and adapted models separately.
Review Nemotron terms before downloading. Its profile is prepared, not a measured result.

Record model/revision, seed, prompt, context/generation limits, training configuration,
data fingerprint, valid/invalid prediction counts, device, timing, and peak memory.
Use a distinct output directory per model/run. Do not call a configuration file evidence
that a model has been executed.

## Final status and advanced learner handoff

The three-task implementation and local GPU engineering verification are complete;
the small trained models are not reliable research or production systems. See
[final status and prioritized next experiments](EXPERIMENTS.md#final-status-and-advanced-learner-next-steps).
Start with a fixed-model GoEmotions data-size learning curve, then improve fictional
annotations and dialogue evaluation before changing model size. Larger models,
full-corpus runs, and human quality validation remain learner experiments, not
completed or implied results.
