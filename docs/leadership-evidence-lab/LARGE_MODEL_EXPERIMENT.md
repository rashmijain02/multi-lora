# Larger-model empathy experiments on DGX Spark and equivalent machines

**Status:** learner experiment proposal, not measured large-model results.
**Prepared/source access date:** 2026-11-10.
**Recommended starting point:** Qwen2.5-7B, then 14B, using BF16 LoRA on one device.
These are continuity baselines, not a current-model ranking. For broader exploration,
shortlist SmolLM3, Ministral 3, Gemma 4, and gpt-oss alongside Qwen and Nemotron.
32B is an optional capacity experiment; 70B-class QLoRA is an advanced extension.

**Implementation update:** the [shared experiment workflow](EXPERIMENTS.md) now
supports original fictional data, GoEmotions emotion classification, and
EmpatheticDialogues response generation with small local verification profiles.
The larger-model shortlist remains exploratory; working small-model pipelines are
not evidence that every listed architecture is supported.

This extends the [initialization](README.md) and [research proposal](PROPOSAL.md).
The question is whether larger models, more independently labeled examples, or better
output control improve **contextual empathy-expression classification**. It is not
whether a bigger model can diagnose empathy or assign people to leadership categories.
The [local measurements](VALIDATION.md) show why output reliability and label accuracy
must be investigated separately.

## 1. Learning objectives and hypotheses

Learners will reproduce the lexical/unadapted/LoRA comparison, measure memory and
throughput, build group-disjoint data splits, and decide whether extra compute is useful.

| Question | Controlled comparison | Evidence needed |
|---|---|---|
| Does model size help? | Qwen2.5 0.5B, 7B, 14B; optionally 32B, with the same task and data | Per-mechanism scores, valid coverage, paired errors, and measured cost |
| Does adaptation help? | Each instruction model versus its own LoRA adapter | Same evaluation prompt, generation settings, split, and base revision |
| Is the bottleneck formatting? | Unconstrained generation versus a separately implemented constrained-decoding arm | Strict JSON validity, evidence validity, and label accuracy reported separately |
| Does data help more than size? | Nested 500 / 2,000 / 5,000 labeled training-example subsets | Same held-out cohorts, documented training exposure, and learning curves |
| Does performance transfer? | Fictional support versus a separately approved, independently labeled domain | Domain-specific results; no pooled score concealing domain shift |

These are hypotheses, not expected outcomes. A smaller model or lexical baseline winning
is a valid result. No public dataset below establishes workplace leadership validity.

## 2. Hardware: 128 GB is not one interchangeable configuration

**Confirmed:** DGX Spark uses a GB10 Grace Blackwell processor, an Arm CPU, and
128 GB of unified CPU/GPU system memory [S1]. This is **not 128 GB of dedicated VRAM
plus additional host RAM**. The OS, preprocessing, model loading, and training share it.
An x86 workstation with dedicated GPU memory has different capacity and bandwidth.

**Planning assumptions, not measurements:** begin with at least 20% free memory after
the representative training pilot. More may be needed for loading, validation, and
checkpoint saving. Do not treat free GPU allocator memory as total free Spark memory.

| Machine | Recommended first experiment | Escalation only after measurement |
|---|---|---|
| Single 24 GB GPU | 7B short-context inference; 7B QLoRA with a reviewed compatible stack | BF16 training may not fit; QLoRA is not implemented here |
| Single 48 GB GPU | 7B BF16 LoRA, microbatch 1 | 14B short-context BF16 LoRA if the full pilot fits |
| Single 80-128 GB GPU | 7B and 14B BF16 LoRA | 32B BF16 LoRA if activations, validation, and saving fit |
| DGX Spark, 128 GB shared memory | 7B, then 14B BF16 LoRA in an Arm64/Blackwell-compatible environment | 32B capacity pilot; optional 70B-class QLoRA in a separate implementation |
| Multiple GPUs totaling up to 128 GB | Start with a model fitting one GPU | Sharding requires a new distributed recipe; memory does not pool automatically |

For orientation, BF16 frozen weights alone cost approximately `parameters * 2 bytes`:
7.6B is 15.2 GB, 14.7B is 29.4 GB, 32.5B is 65 GB, and 72B is 144 GB,
in decimal units. These are **weight payloads, not training-memory estimates**.
Activations, adapters, gradients, optimizer states, temporary buffers, and generation
KV caches add memory. LoRA freezes base weights; it does not eliminate activations.
Full-parameter fine-tuning is outside the core proposal.

A 72B model's theoretical 4-bit weight payload is about 36 GB, but real quantized
storage and training require more. Nvidia's advertised model-size limits [S2] depend
on precision and recipe; they do not prove this workshop can train those models.
Fitting in memory also does not imply acceptable throughput. Do not extrapolate FP4
marketing compute to BF16 training speed or assume a multi-GPU server's speed on Spark.

## 3. Models and training ladder

Use the Qwen2.5 family to limit architecture changes in the primary size comparison.
These are continuity choices, not a claim that they are the newest or best available
models. The Nemotron and other-family shortlists below add separate exploratory arms;
they are not drop-in replacements or controlled parameter-count ablations.

| Model | Role | Initial method | Readiness |
|---|---|---|---|
| Qwen2.5-0.5B-Instruct | Small-model reference | Existing FP16 LoRA | Local results recorded; not a reliable classifier |
| Qwen2.5-7B-Instruct | Primary larger baseline | BF16 inference and LoRA | Pinned `configs\qwen-large.json`; no recorded execution |
| Qwen2.5-14B-Instruct [S4] | Recommended main size comparison | BF16 inference and LoRA | Learner-created pinned profile required |
| Qwen2.5-32B-Instruct [S5] | Optional capacity/performance comparison | BF16 LoRA only after a pilot | Learner-created pinned profile required |
| Llama-3.1-Nemotron-Nano-8B-v1 | Optional cross-family comparison | Existing BF16 profile | Pinned `configs\nemotron-large.json`; separate NVIDIA/Llama terms |
| 70B/72B-class instruction model | Advanced systems extension | Reviewed 4-bit QLoRA recipe | Not supported by the current loader; not a core deliverable |

The 14B and 32B cards declare Apache-2.0 [S4-S5]; review the exact selected revision
and preserve its terms. Never assume every model in a family has identical licensing.
Pin model and tokenizer to the same immutable commit. Store adapters separately from
base weights and associate every adapter with its exact base revision.

### NVIDIA Nemotron family shortlist

Start with the existing 8B profile for continuity. Add the newer hybrid/MoE models
only after the standard Transformer experiment works. "Nano" is a product-family
name, not a promise of small resident memory.

| Exact model identifier | Why explore it? | Memory/training approach | Compatibility and terms |
|---|---|---|---|
| `nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1` [S10] | Lower-cost dense control: can a smaller NVIDIA model match 7B/8B? | BF16 inference, then short-context LoRA after a pilot | Standard dense Transformer; new pinned profile and save/reload verification required; NVIDIA Open Model License plus Llama 3.1 terms |
| `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` | Recommended first NVIDIA comparison against Qwen 7B | Existing BF16 profile and single-device LoRA recipe | Already configured, not measured here; NVIDIA/Llama terms; keep its own run directories |
| `nvidia/NVIDIA-Nemotron-Nano-9B-v2` [S11] | Hybrid Mamba-2/Transformer efficiency and output-quality comparison | Inference first; LoRA only with a reviewed hybrid-compatible implementation | Card's Transformers example uses remote model code; current loader disables it; NVIDIA Open Model License |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` [S12] | Advanced hybrid MoE comparison with relatively few active parameters | About 60 GB BF16 total-weight payload before runtime overhead; inference pilot before any LoRA | Card reports 30B total and 3.5B active parameters; native Transformers integration requires 5.3.0+, beyond this workshop's 4.57.6 pin; NVIDIA Nemotron Open Model License |
| `nvidia/Llama-3_3-Nemotron-Super-49B-v1_5` [S13] | Optional higher-capacity NVIDIA quality reference | About 98 GB BF16 weight payload alone; prefer a reviewed quantized inference recipe on a 128 GB machine; not a default BF16 training target | NAS-customized, nonuniform Transformer blocks; custom runtime/module review required; NVIDIA Open Model License plus Llama 3.3 terms |

Memory payloads above are arithmetic planning estimates in decimal GB, not device
measurements. The 30B MoE still needs its total weights resident in the ordinary
single-device recipe: **3.5B active does not mean 3.5B-weight memory**. Expert offload
would be a separate systems experiment. The 49B BF16 model leaves little headroom
on Spark for the OS, activations, KV cache, and loading; do not assume it can train.

Reasoning control differs by checkpoint. Nano 4B v1.1 and the existing Nano 8B v1
use `detailed thinking off`; Nano 9B v2 and Super 49B v1.5 document `/no_think`;
Nemotron 3 Nano uses `enable_thinking=False` in its chat template [S10-S13].
The default Nemotron prompt fallback sends `detailed thinking off`. That is not
validated for newer checkpoints. The shared experiment workflow can instead pass
explicit native `chat_template_kwargs`, but each checkpoint's controls and output
format must still be tested before using it in the JSON-only benchmark.

Keep the current `trust_remote_code=False` default. A card showing
`trust_remote_code=True` is a review requirement, not an instruction to enable it.
If approved custom code is necessary, review/pin the exact source and run it only
in a separately approved environment. Check hybrid/MoE adapter target modules,
trainable parameter counts, backward passes, and checkpoint reloads: matching a few
attention projections is not evidence that the full architecture is appropriately
adapted. Inference runtime support does not establish PEFT training support.

### Other models worth exploring

The broader shortlist is based on official cards and research checked on 2026-11-10,
not a claim that Qwen and Nemotron are the only worthwhile open-weight families.
Use instruction-tuned checkpoints for the classification comparison. When a row
names a family, select and pin its exact instruction checkpoint before execution.
Do not count a Qwen-derived fine-tune as an independent architecture family.

| Model identifier(s) or family | Experimental value | Starting plan and limitation |
|---|---|---|
| `Qwen/Qwen3-8B`, `Qwen/Qwen3-14B`, `Qwen/Qwen3-32B` [S14] | Dense newer-generation comparison; investigate whether non-thinking instruction following improves structured empathy outputs | Apache-2.0; start with 8B or 14B BF16 inference/LoRA, then capacity-test 32B; new pinned profiles and explicit reasoning controls required |
| Google Gemma 4: 12B, 26B-A4B, 31B [S16] | Independent family with dense/MoE alternatives, configurable reasoning, and a July 2026 technical report | Apache-2.0; prioritize dense 12B, then optionally 31B; 26B-A4B is a separate MoE systems arm. Card reports about 11.95B, 25.2B total/3.8B active, and 30.7B parameters respectively; new processor/template and training integration required |
| `mistralai/Ministral-3-14B-Instruct-2512` [S17] | Independent-family instruction-following and structured-JSON candidate; the family also offers 3B/8B options | Apache-2.0; inference first. This Instruct checkpoint is FP8, not an ordinary BF16 LoRA starting point; review a supported training representation/recipe. BF16 Base and Reasoning variants are different experimental conditions |
| `openai/gpt-oss-20b` [S18] | Local reasoning/structured-output specialization with 21B total/3.6B active parameters | Apache-2.0; MXFP4-aware inference first, then a reviewed adaptation pilot. Native Harmony formatting, channel handling, and training backend support are required; the card's 16 GB inference claim is not a training-memory estimate |
| `meta-models/Muse-Glimmer-30B` [S19] | August 2026 dense agentic release; independent larger-family comparison with vendor-reported instruction-following evaluations | Apache-2.0; quantized inference first, then a measured BF16 LoRA pilot on suitable hardware. Card reports about 29.6B parameters; review multimodal loading, reasoning controls, and adapter targets |
| `zai-org/GLM-4.7-Flash` [S20] | MIT-licensed 30B-A3B MoE comparison: investigate quality versus dense models at similar resident-weight scale | About 60 GB BF16 total-weight payload before overhead; inference first. Review current runtime and expert-adapter support; vendor examples are not validation against this workshop's dependency pins |
| `HuggingFaceTB/SmolLM3-3B` [S21] | Low-cost dense control with open training details; tests whether better small-model adaptation can replace scaling | Apache-2.0; prioritize short-context BF16 inference/LoRA after the compatibility pilot. Explicitly disable thinking for the non-thinking arm; compatibility is not yet measured here |
| `LiquidAI/LFM3-1.7B` [S22] | October 2026 tri-hybrid efficiency/specialization experiment, not a large-model escalation | LFM Open License v1.0, not Apache/MIT; review terms and convolution/attention training support. Its roughly 1 GB 4-bit deployment claim does not establish fine-tuning memory |
| `mistralai/Mistral-Small-3.2-24B-Instruct-2506` [S15] | Independent-family instruction-following and structured-output comparison around the 24B tier | Apache-2.0; inference first on 80-128 GB-class hardware; card estimates about 55 GB GPU memory for BF16/FP16 inference, not training; multimodal model/tokenizer integration is not a drop-in causal-LM profile |

**Large quantized inference references, not default training targets:**
`openai/gpt-oss-120b` has 117B total/5.1B active parameters; its card describes
MXFP4 inference on one 80 GB GPU [S18]. `mistralai/Mistral-Small-4-119B-2603`
has 119B total/6.5B active parameters and an officially linked NVFP4 checkpoint
[S23]. Both declare Apache-2.0. Their BF16 weight payloads alone are approximately
234 GB and 238 GB, respectively, beyond a single 128 GB machine. Any quantized
inference trial must verify actual memory, backend support, and throughput on the
learner's hardware; no quantized training fit is established here.

For Qwen3, use the post-trained identifiers above, not their `-Base` variants.
The card documents `enable_thinking=False` for non-thinking output. Current prompt
rendering in the shared experiment workflow supports this through
`chat_template_kwargs: {"enable_thinking": false}` in model overrides. Verify the
raw continuation is JSON-only before comparing label
scores. Keep any reasoning-enabled arm separate, with its own generation budget,
decoding settings, and final-answer extraction; do not silently strip extra output
to make the strict primary arm pass.

For Mistral Small, use the model-card-supported processor/model class and tokenizer
format in a separate reviewed integration. Keep this experiment text-only; vision
capability is not evidence of empathy accuracy. Verify response-only training masks
after any processor/template change. Apply the same gate to Gemma, Ministral, and
Muse rather than assuming the current causal-LM loader supports them.
If a local serving runtime is used, bind it to loopback and retain the same
post-generation validation and cost accounting.

gpt-oss requires Harmony-formatted conversations and explicit final-channel handling;
do not score a raw multi-channel continuation as if it were ordinary assistant JSON.
Define and test extraction before evaluation, preserve raw output locally under the
same privacy rules, and report channel/extraction failures separately. A reasoning
model's low-effort mode is not necessarily a non-thinking mode. Record its full token
budget and latency, including reasoning, rather than comparing final JSON length alone.

**Suggested exploration order:** reproduce Qwen2.5 7B/14B and the existing Nemotron
Nano 8B arm first. For breadth, shortlist SmolLM3-3B as an efficiency control,
Ministral 3 14B and Gemma 4 12B as independent-family alternatives, and gpt-oss-20b
as a separate format/quantization integration. Admit each only after its environment
and training gate passes; shortlist membership is not execution readiness.
Choose at most one larger reference initially: Gemma 4 31B or Muse Glimmer 30B.
For a systems-focused extension instead, choose one of GLM-4.7-Flash, Gemma 4
26B-A4B, or Nemotron 3 Nano. Qwen3, Mistral Small 3.2, and the other NVIDIA
checkpoints remain optional. Do not run every model merely because it fits a list.

### Reading benchmarks and recent research

The original Hugging Face Open LLM Leaderboard officially retired in March 2025
[S24]. Do not cite its historical ranking as a current recommendation. Hugging Face
likes, downloads, and trending lists indicate adoption or attention, not accuracy.
Its Open Evals resources can help locate task-specific evaluations.

Artificial Analysis provides independent capability and efficiency comparisons
[S25], but its broad leaderboard is not an empathy benchmark or a list of models
that fit this hardware. Record model/checkpoint version, evaluation date, precision,
reasoning effort, scaffold/tools, and token budget when citing a result. Manufacturer
model-card comparisons are **vendor-reported**, even when they use familiar benchmark
names; do not present them as independent replication or compare unlike settings.
No current Arena or LiveBench ranking is asserted here: Arena access was blocked
and the accessible LiveBench page did not expose usable current scores.

For this task, use instruction-following evaluations such as IFBench as supporting
evidence, not a proxy for empathy accuracy. The JSONSchemaBench study [S26] separates
constraint coverage, efficiency, and generated-output quality across decoding systems.
This motivates a separately measured constrained-decoding arm, not an assumption
that a model advertising JSON support will pass our schema or quote checks.

The selection criteria remain local gold-label macro-F1, all-example correctness,
schema/evidence-valid coverage, human-reviewed rationale support, and measured cost.
Strong math, coding, agentic, or multimodal scores do not establish any of these.
There is **no verified empathy ranking for the newly shortlisted models** in this
proposal, and their inclusion is a source-backed experimental recommendation, not
a measured superiority claim.

### Environment gate

On Spark, use the device's supported Linux software stack and an approved NVIDIA
PyTorch container/environment compatible with Arm64 and Blackwell [S3]. Review and pin
the container digest and dependencies before use; do not blindly execute downloaded
playbook scripts. On other hardware, use a compatible Linux CUDA/PyTorch environment.

The workshop lock selects a CUDA 12.8 PyTorch index. **Do not assume `uv sync` is a
validated Spark setup** or let it replace a working vendor PyTorch installation.
Provision a separate reviewed environment containing the workshop and required
Transformers/PEFT/scikit-learn dependencies; record deviations from `pyproject.toml`.
Confirm imports, CUDA availability, BF16 support, model loading, a backward pass,
adapter save/reload, and validation generation before scheduling a long run.

Quantization libraries and optimized attention kernels need their own Arm64/Blackwell
compatibility check. FP4 hardware support is not the same as an installed NF4 QLoRA
backend. Do not install an unreviewed acceleration package just to make a run fit.

### Pilot and resource budget

Start with batch 1, total training sequence length 1,024, rank 8, and gradient
accumulation 8, matching the existing larger profile. Freeze these for the replay.
For expanded data, select context/output budgets on training and validation only.
Do not silently truncate the support response, evidence, or target JSON; audit token
lengths before training. Longer inference output does not repair truncated SFT targets.

Before each full run, execute 20-50 optimizer steps on representative long training
examples, including validation and adapter saving/reloading. Record peak system memory,
CUDA allocated/reserved memory, swap activity, elapsed time, and processed tokens.
On Spark, system-level memory is essential because allocator figures are incomplete.

Estimate total duration from measured optimizer-step time plus evaluation and saving,
not parameter count alone. Agree a learner time/storage budget before escalation.
If memory or time is unacceptable, stop, reduce context/microbatch, or choose a smaller
model. Changing precision or enabling checkpointing creates a new recorded experiment.
Do not change shared-machine drivers, kill other processes, or clear global caches.

## 4. Dataset recommendations: size must match the supervision

**There is no verified, unrestricted, million-example dataset here with all three
human empathy-mechanism labels and rationale spans.** Large dialogue corpora are useful,
but their size must not be presented as the number of empathy-labeled examples.

| Source | Verified scale / unit | Useful experiment | Terms and main limitation |
|---|---|---|---|
| [Original fictional expansion](data/README.md) | Proposed 5,000 training + 1,000 validation + 1,000 fresh test exchanges | Best continuity with the existing three-mechanism task | Author-created goal, not an available corpus; independent human labels needed; teaching validity only |
| [GoEmotions](https://huggingface.co/datasets/google-research-datasets/go_emotions) [S6] | Simplified: 43,410 train, 5,426 validation, 5,427 test comments; raw: 211,225 annotation rows, not independent comments | Large auxiliary multi-label emotion-classification task and domain-shift study | Card declares Apache-2.0; Reddit text/metadata need minimization; emotions are not empathy-mechanism labels |
| [EmpatheticDialogues](https://huggingface.co/datasets/facebook/empathetic_dialogues) [S7] | About 25,000 conversations; HF has 76,673 / 12,030 / 10,943 utterance rows | Optional noncommercial response-generation adaptation, or a separately human-annotated classification subset | CC BY-NC 4.0; conversation emotion context is not a response empathy score |
| [EPITOME](https://github.com/behavioral-data/Empathy-Mental-Health) [S8] | Paper/repository describe roughly 10,000 annotated post-response pairs across the study | Closest label/rationale match after access and reuse approval | Count the admitted subset, not the entire study; Reddit files available, TalkLife needs separate permission; sensitive domain and license review |
| [UltraChat 200k](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k) [S9] | 207,865 `train_sft` and 23,110 `test_sft` dialogues in the SFT splits | Optional general-instruction retention or throughput control; not the primary task | Card declares MIT; ChatGPT-generated, not human empathy annotations; review upstream provenance/terms |

**Recommendation:** begin with original fictional expansion for the exact task;
use GoEmotions as the larger, clearly separated auxiliary benchmark. Add
EmpatheticDialogues only if its noncommercial terms fit the learner's use. Prefer
approved EPITOME annotations over inventing equivalent labels, but do not assume
access permission. UltraChat is optional and lower priority than better task labels.

### Where to obtain each dataset

These are acquisition instructions, not commands executed by this proposal. Review
the source's current license and access conditions before downloading. Use a
designated local storage location excluded from Git; do not save private text or
access credentials in notebooks, reports, or committed configuration.

| Dataset | Download location | How to obtain and what to select |
|---|---|---|
| Original fictional data | [Workshop data guide](data/README.md) | The existing 36 fictional records are supplied with the workshop; no external download is needed. The proposed larger expansion does not exist as a downloadable dataset: author and independently label it using the documented schema |
| GoEmotions | [Hugging Face files: simplified](https://huggingface.co/datasets/google-research-datasets/go_emotions/tree/main/simplified) | Open **Files and versions**, select an immutable repository commit, and download every Parquet shard for the `simplified` train/validation/test splits. Prefer this configuration initially; `raw` contains repeated annotation rows and additional identifying metadata |
| EmpatheticDialogues | [Official dataset archive](https://dl.fbaipublicfiles.com/parlai/empatheticdialogues/empatheticdialogues.tar.gz), linked by the [original repository](https://github.com/facebookresearch/EmpatheticDialogues#dataset) | Download the `.tar.gz` data archive and extract it locally; retain its official train/validation/test CSV splits and conversation identifiers. The archive is data, not a requirement to install or run the upstream model code. Record a checksum because this download URL is not commit-pinned; respect CC BY-NC 4.0 |
| EPITOME Reddit subset | [Official dataset folder](https://github.com/behavioral-data/Empathy-Mental-Health/tree/master/dataset) and [access instructions](https://github.com/behavioral-data/Empathy-Mental-Health#dataset-access-instructions) | After reuse/privacy review, select an immutable repository commit and download `emotional-reactions-reddit.csv`, `interpretations-reddit.csv`, and `explorations-reddit.csv`. All three are needed for the mechanism comparison; align by seeker/response identifiers, not row position. Samples are not the full corpus |
| EPITOME TalkLife subset | [Official access instructions](https://github.com/behavioral-data/Empathy-Mental-Health#dataset-access-instructions) | Follow the authors' contact procedure to request noncommercial access from TalkLife. It is not an unrestricted public download; do not use mirrors to bypass permission or assume approval for Reddit also covers TalkLife |
| UltraChat 200k | [Hugging Face data files](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k/tree/main/data) | Select an immutable repository commit and download all `train_sft-*` and `test_sft-*` Parquet shards for the optional SFT experiment. Keep these splits separate; `train_gen`/`test_gen` are different experimental splits, not extra independent SFT examples |

For Hugging Face and GitHub, replace the moving branch in the file URL with the
selected commit and record it in the source register. Retain the dataset card,
license, file checksums, and downloaded split/shard inventory; verify completeness
before preprocessing. Browser downloads avoid requiring a new package or executing
upstream scripts. Do not fetch dataset rows merely to test that an access link works.

**Downloading is not automatically ingestion.** The shared experiment workflow
supports pinned GoEmotions and EmpatheticDialogues preparation for their separate
tasks. EPITOME and UltraChat still require reviewed ingestion/task extensions.
The legacy fictional loader remains fictional-only: do not relabel public data
`fictional: true` or pass its raw files to the original fictional training CLI.

For original data, pilot 500 labeled training exchanges before authoring thousands.
Include clear and borderline 0/1/2 responses, context dependence, generic reassurance,
unsupported assumptions, irrelevant questions, and counterexamples to warm wording.
Keep scenario templates and all paraphrases in the same split. Record human-authored
versus model-assisted provenance. A model may suggest labels, but its suggestions are
not independent human ground truth or a research annotation-agreement study.

For a research-quality evaluation, use two independent annotators for the held-out
cohorts, blinded to model predictions; report pre-adjudication agreement, the
adjudication procedure, and unresolved ambiguity. If self-study resources do not allow
this, reduce the dataset target and label the result as author-labeled teaching evidence.
Do not use the test set for rubric revisions; reserve a fresh cohort after revisions.

### Admission, splitting, and privacy gates

For every source, record URL, immutable revision/checksum, license and approval,
collection/annotation provenance, permitted outputs, retention, and dataset fingerprint.
Keep raw downloaded corpora in a separately designated local location excluded from
Git. The current workshop does not ignore all of `data`; do not place a corpus there
and assume it is protected. Review reports too: inference reports contain raw outputs.

Deduplicate before custom splitting. Group dialogue turns by conversation, EPITOME
responses by seeker/thread, and fictional examples by scenario family. Preserve official
splits for benchmark comparability, but audit group overlap and disclose any limitations.
If creating stronger group-disjoint splits, version them and report results separately.
GoEmotions' raw annotation rows must not become duplicated independent examples.
For UltraChat, group by prompt/conversation and near-duplicate clusters; do not merge
its SFT and generation splits and call the sum independent training data.

Remove author handles and unrelated metadata; do not build person profiles.
No automatic workplace-mail ingestion, no cloud upload of source text, and no release
of sensitive quotations or model outputs. Review licensing and memorization risks
before publishing adapters. Default deliverables are recipes and aggregate metrics.

## 5. Experimental sequence

### Stage A: reproduce the existing fictional task

Keep the 36 fixtures, original split, prompt, 192-token generation cap, seed, and
100-step larger-model profile unchanged. Run the lexical baseline and unadapted/adapted
7B pair; optionally repeat with Nemotron 8B in separate directories. This is a systems
replay, **not an equal-budget comparison** with the recorded 30-step 0.5B run.
The eight-example test cohort has already informed public observations and is too
small for a new generalization claim; do not treat it as a new sealed benchmark.

Commands below use **PowerShell 7**, including on a Linux learner machine if available.
Start at the repository root in the approved, activated Python environment described
above. `Join-Path` creates native paths for Python on either host. These commands use
the existing API; they do not provision the Spark environment.

```powershell
Set-Location workshops\leadership-evidence-lab
# All following commands start in this workshop directory.
$config = Join-Path configs qwen-large.json
$run = Join-Path artifacts qwen7b-replay-seed42
$adapter = Join-Path $run adapter
$baseReport = Join-Path $run base-validation.json
$adaptedReport = Join-Path $run adapted-validation.json

python -c "import torch; assert torch.cuda.is_available(); assert torch.cuda.is_bf16_supported(); print(torch.__version__, torch.cuda.get_device_name(0))"
python -m empathy_lab validate
python -m empathy_lab baseline --split validation
python -m empathy_lab infer --config $config --split validation --report $baseReport
python -m empathy_lab train --config $config --output $adapter
python -m empathy_lab infer --config $config --split validation --adapter $adapter --report $adaptedReport
```

Check each exit status before the next command. Use a new run directory rather than
overwriting an adapter. After recording validation choices, use `--split test` with
distinct report names for the descriptive replay test comparison. Repeat the test
baseline as well. Loading the adapter at inference demonstrates save/reload compatibility.

For Nemotron, select `configs\nemotron-large.json` using `Join-Path` and change every
run directory. The package already disables its reasoning mode. Do not mix its
adapter with Qwen weights.

### Stage B: compare 7B and 14B on an expanded fictional cohort

Create a new profile by copying `configs\qwen-large.json`. Set `model_id` to
`Qwen/Qwen2.5-14B-Instruct` and `revision` to the verified **40-character commit hash**
from that model's approved snapshot, not `main`. For 32B use its own identifier/hash.
These profiles are learner-created artifacts, not files supplied by this proposal.

The model profile loader remains strict and flat. Keep `device` as `cuda`, BF16,
and rank 8 initially. Optional fields now include LoRA targets/alpha/dropout,
warmup/evaluation cadence, `gradient_checkpointing`, and native chat-template options.
Do not add `load_in_4bit`, `device_map`, or undocumented keys: the loader rejects them.
In particular, `device: auto` does not implement GPU sharding in this code.

Author the expanded JSONL to the existing fictional schema, with labels, rationales,
verbatim assistant evidence spans, and scenario-disjoint splits. Use the existing
`--data` option **before** the subcommand. For example, after creating the dataset:

```powershell
# Still in workshops\leadership-evidence-lab.
$data = Join-Path data fictional_support_expanded.jsonl
python -m empathy_lab --data $data validate
python -m empathy_lab --data $data baseline --split validation
```

Pass the same `--data $data` prefix to each `train` and `infer` invocation in Stage A,
with new profiles and run directories. Never accidentally train on the default
36 records while reporting the expanded dataset's size.

For each training-data tier, match effective batch size and dataset exposure across
model sizes. Start with one epoch; use validation to select among a small preregistered
set of one-to-three-epoch budgets. With one device:

`effective batch = microbatch * gradient accumulation`

`optimizer steps per epoch ~= ceil(training examples / effective batch)`

Record actual consumed examples/tokens; a fixed 100-step recipe is not a universal
large-dataset budget. Use one seed for capacity pilots, then seeds 17, 42, and 73 for
finalist configurations. The main 7B/14B unadapted/adapted comparison is sufficient;
32B and cross-family runs are optional, not prerequisites.

Select a generation cap on validation that can accommodate all three rationale/span
objects, for example comparing 192 with 384 or 512 tokens. Freeze it across the
new benchmark arms and report the change from Stage A. Do not use format-repair
retries in the primary arm. A retry or constrained-decoding arm has its own cost/results.

### Stage C: larger public datasets, as separate tasks

The original loader **requires `fictional: true`** and the three mechanism labels.
It remains unchanged for real-person admission: **never mark public conversations
fictional to bypass that restriction**.

Use the [shared experiment commands](EXPERIMENTS.md) and supplied GoEmotions or
EmpatheticDialogues experiment JSON instead. Preparation pins source revisions or
archive hashes, audits full source splits, reconstructs dialogues, removes cross-split
duplicate inputs, selects reproducible subsets, and fingerprints per-split files.
Training reads train/validation only; test evaluation is a separate explicit command.
These audited splits are not untouched official benchmark submissions.

For GoEmotions, retain the real multi-label emotion task and report fixed-label
micro/macro-F1. The supplied lexical baseline uses a documented 0.5 threshold with an
argmax fallback; any threshold tuning belongs on validation. Do not turn `caring`
into an empathy score. EmpatheticDialogues trains listener-response generation,
not supervised mechanism classification; its token overlap and response likelihood
are not empathy metrics. A mechanism benchmark needs independent annotations.
EPITOME conversion remains future work and must
align mechanism records by identifiers and handle missing labels/rationales explicitly,
not fill them with zeros or invented evidence.

Auxiliary-then-task adaptation is not implemented. If adding it, compare direct task LoRA against auxiliary-then-task
adaptation using the same final gold evaluation cohort; report the added token budget.
Do not pool emotion, generation, and empathy scores into one accuracy number.

## 6. Evaluation and decision gates

Preserve the current per-mechanism fixed-class macro-F1, balanced accuracy, confusion
matrices, and strict invalid-output accounting. Valid-only scores are conditional:
a model answering three easy examples must not appear better than one answering all.
Always publish valid/invalid counts beside scores and distinguish JSON failures,
schema failures, quote failures, and output truncation in the analysis.

Additional analyses and implementation status:

- Implemented in shared experiments: all-example per-mechanism correct-score rate,
  with correct valid scores divided by all evaluation examples. Invalid output is
  a failure, never a zero-empathy prediction.
- Proposed human-reviewed rationale support: an exact quotation establishes source membership,
  not whether it justifies the label. Audit correctness separately.
- Paired, scenario/conversation-cluster bootstrap confidence intervals and seed spread.
  Do not treat related turns or random seeds as independent human observations.
- Validation-selected coverage/abstention rules if added; the current model has no
  calibrated confidence or implemented insufficient-evidence class.
- End-to-end examples/second, input/output tokens, training duration, peak memory,
  generation latency, and disk usage. Record warm-up and batch-size conditions.

Suggested operational gate: at least 95% schema-and-evidence-valid outputs on a
sufficiently sized validation cohort before calling a classifier usable for the lab.
This is a proposed engineering threshold, not psychological validation. If no model
passes, report failure and investigate on training/validation rather than revisiting
the sealed test. Freeze model/configuration choices before one final test evaluation.

Recommend 14B over 7B only if it improves the preregistered primary outcome without an
unacceptable coverage/cost tradeoff. Report uncertainty and negative results. Never
infer fairness, stable empathy, clinical utility, or leadership ability from these tests.

## 7. Learner deliverables and implementation boundary

Deliver a source/license register, split/data fingerprints, pinned environment and
model profiles, run matrix, baseline/unadapted/adapted comparison, resource measurements,
error taxonomy, and a short decision explaining whether scaling was worthwhile.
Publish reviewed aggregate reports; clear notebook outputs before publication.

**Available now:** original fictional-only APIs plus configurable three-task
preparation/validation, train-only baselines, single-device unquantized LoRA with
optional gradient checkpointing, strict post-generation task checks, aggregate-only
reports, pinned adapters, CLI, and notebooks. These checks do not constrain decoding
while tokens are generated. See [local verification](VALIDATION.md).

**Proposed work, not implemented:** EPITOME/UltraChat ingestion, auxiliary-then-task
adaptation, QLoRA, distributed training, constrained decoding, experiment scheduling,
confidence calibration, and cluster-bootstrap reporting.
Checkpoint-specific reasoning controls and hybrid/MoE/multimodal integrations from
the extended shortlist also remain proposed. There is no claim of a Spark run,
14B/32B result, or execution of the newly shortlisted model families. The recorded
public-data experiments are small local engineering checks, not large-data findings.

Complete the fictional 7B/14B study before investing in 70B-class systems work. More
independently annotated, relevant examples are usually a better next learning investment
than maximizing parameter count; test that hypothesis rather than assuming it.

## Sources

Official hardware/model documentation, original repositories/cards, research papers,
and evaluation resources were consulted on 2026-11-10. Hardware facts and
card-declared counts/licenses are source-backed; capacity tiers, budgets, data targets,
shortlist priorities, and acceptance thresholds above are proposals. Vendor benchmark
claims are not independently reproduced here. Before execution, pin snapshots and
recheck terms and platform compatibility.

- **[S1]** [NVIDIA DGX Spark hardware guide](https://docs.nvidia.com/dgx/dgx-spark/hardware.html):
  Arm CPU, GB10, unified memory, and bandwidth.
- **[S2]** [NVIDIA DGX Spark product page](https://www.nvidia.com/en-us/products/workstations/dgx-spark/):
  advertised inference/fine-tuning capacities, not workshop measurements.
- **[S3]** [NVIDIA PyTorch fine-tuning playbook](https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/pytorch-fine-tune):
  vendor container approach, PEFT recipes, and platform compatibility cautions.
- **[S4]** [Qwen2.5-14B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct):
  architecture, parameter count, runtime usage, and declared license.
- **[S5]** [Qwen2.5-32B-Instruct model card](https://huggingface.co/Qwen/Qwen2.5-32B-Instruct):
  architecture, parameter count, runtime usage, and declared license.
- **[S6]** [GoEmotions dataset card](https://huggingface.co/datasets/google-research-datasets/go_emotions):
  split counts, raw annotation rows, labels, license, and identifying metadata.
- **[S7]** [EmpatheticDialogues original repository](https://github.com/facebookresearch/EmpatheticDialogues)
  and [HF dataset card](https://huggingface.co/datasets/facebook/empathetic_dialogues):
  conversation versus utterance counts and noncommercial license.
- **[S8]** [EPITOME original repository](https://github.com/behavioral-data/Empathy-Mental-Health):
  three mechanisms, rationale annotations, study scale, and access instructions.
- **[S9]** [UltraChat 200k dataset card](https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k):
  synthetic provenance, SFT split sizes, and declared license.
- **[S10]** [Llama-3.1-Nemotron-Nano-4B-v1.1 model card](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Nano-4B-v1.1):
  dense architecture, reasoning controls, and NVIDIA/Llama terms.
- **[S11]** [NVIDIA-Nemotron-Nano-9B-v2 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2):
  hybrid architecture, remote-code usage example, reasoning controls, and license.
- **[S12]** [NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16):
  total/active parameters, native Transformers version, Spark inference guidance,
  reasoning controls, and NVIDIA Nemotron license.
- **[S13]** [Llama-3.3-Nemotron-Super-49B-v1.5 model card](https://huggingface.co/nvidia/Llama-3_3-Nemotron-Super-49B-v1_5):
  NAS architecture, runtime examples, reasoning controls, and NVIDIA/Llama terms.
- **[S14]** [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B),
  [Qwen3-14B](https://huggingface.co/Qwen/Qwen3-14B), and
  [Qwen3-32B](https://huggingface.co/Qwen/Qwen3-32B) model cards:
  dense model sizes, declared licenses, and checkpoint-specific usage guidance.
- **[S15]** [Mistral-Small-3.2-24B-Instruct-2506 model card](https://huggingface.co/mistralai/Mistral-Small-3.2-24B-Instruct-2506):
  instruction-following motivation, multimodal runtime/tokenizer requirements,
  declared license, and inference-memory estimate.
- **[S16]** [Gemma 4 model card](https://huggingface.co/google/gemma-4-31B)
  and [technical report](https://arxiv.org/abs/2607.02770):
  family sizes, dense/MoE architectures, configurable reasoning, and Apache-2.0 terms.
- **[S17]** [Ministral 3 14B Instruct model card](https://huggingface.co/mistralai/Ministral-3-14B-Instruct-2512)
  and [Ministral 3 paper](https://arxiv.org/abs/2601.08584):
  instruction/JSON motivation, family variants, FP8 Instruct versus BF16
  Base/Reasoning checkpoints, and Apache-2.0 terms.
- **[S18]** [gpt-oss-20b model card](https://huggingface.co/openai/gpt-oss-20b)
  and [technical report](https://arxiv.org/abs/2508.10925):
  both model sizes, total/active counts, Harmony format, reasoning effort,
  MXFP4 inference claims, fine-tunability, and Apache-2.0 terms.
- **[S19]** [Muse Glimmer 30B model card](https://huggingface.co/meta-models/Muse-Glimmer-30B):
  August 2026 release, dense multimodal architecture, local deployment formats,
  vendor-reported evaluations, reasoning controls, and Apache-2.0 terms.
- **[S20]** [GLM-4.7-Flash model card](https://huggingface.co/zai-org/GLM-4.7-Flash):
  30B-A3B MoE configuration, runtime requirements, vendor evaluations, and MIT terms.
- **[S21]** [SmolLM3-3B model card](https://huggingface.co/HuggingFaceTB/SmolLM3-3B):
  dense architecture, open training details, thinking controls, and Apache-2.0 terms.
- **[S22]** [LFM3-1.7B model card](https://huggingface.co/LiquidAI/LFM3-1.7B)
  and [Liquid AI release article](https://www.liquid.ai/blog/lfm3):
  October 2026 release, tri-hybrid architecture, local specialization, quantized
  deployment claims, and LFM Open License v1.0.
- **[S23]** [Mistral Small 4 model card](https://huggingface.co/mistralai/Mistral-Small-4-119B-2603):
  119B total/6.5B active parameters, officially linked NVFP4 variant, runtime
  requirements, and Apache-2.0 terms.
- **[S24]** [Official Open LLM Leaderboard retirement announcement](https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard/discussions/1135)
  and [Open Evals leaderboard finder](https://huggingface.co/spaces/OpenEvals/find-a-leaderboard):
  March 2025 retirement and discovery of alternative evaluations.
- **[S25]** [Artificial Analysis model leaderboard](https://artificialanalysis.ai/leaderboards/models)
  and its [Hugging Face Space](https://huggingface.co/spaces/ArtificialAnalysis/LLM-Performance-Leaderboard):
  independent general-capability/efficiency evaluation resource, not empathy validation.
- **[S26]** [JSONSchemaBench paper](https://arxiv.org/abs/2501.10868):
  structured-generation evaluation of constraint coverage, efficiency, and output quality.
