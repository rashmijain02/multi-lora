# Workshop 7 Plan: Email-reply QLoRA SFT and checkpoint-initialized GRPO

Workshop 1 trains classification and persona-style LoRA adapters on curated datasets. Real corporate
email threads introduce two harder problems:

1. **Context sufficiency:** many sent replies depend on offline meetings, attachments, or earlier
   threads that are *not* in the incoming quote. Scoring every draft by string overlap against the
   historical reply rewards hallucination.
2. **Thread leakage:** corporate email archives repeat quoted history across replies and forwards
   without canonical thread IDs. A naive random row split leaks held-out conversations into training.

This workshop separates shared utilities (`util\`) from stage-specific trainers (`sft\` and `grpo\`),
operates on prepared `(conversation, reply)` JSONL datasets, fits 12 GB consumer CUDA hardware, and
keeps generated runs and private sample outputs strictly local. See [README.md](README.md) for
commands.

## 1. Architecture and configuration boundaries

- **`util\`:** shared path/ACL/Git-ignore guards (`paths.py`), dataset validation and inferred
  thread-grouped split manifests (`data.py`), model profiles and prompt budgeting (`prompts.py`),
  Unsloth/PEFT loading and identity checks (`models.py`), append-only `metrics.jsonl` telemetry and
  headless Matplotlib diagnostics (`monitoring.py`), and paired held-out evaluation (`evaluation.py`).
- **`tools\prepare_input.py`:** standalone mail-thread converter keeping format-specific MIME,
  mailbox, JSON, plain/quoted-text, and CSV/JSONL normalization decoupled from the SFT/GRPO
  trainers. Message-mode conversion requires explicit reply IDs (`In-Reply-To`/`References`) or
  operator-bounded thread timestamps, strips trailing quote blocks from target replies, renders
  preceding context newest-first, and rejects ambiguous inline quotes, cycles, later messages, or
  verbatim target disclosures. Already-paired CSV/JSONL imports still pass field/disclosure checks,
  though absent message-level metadata means chronological linkage cannot be independently audited.
- **`sft\`:** supervised reply-masked QLoRA trainer (`trainer.py`) and CLI/experiment runner
  (`experiment.py`).
- **Configurable storage and models:** `--input-dir` and `--output-dir` default to source-relative
  `input\enron\` and `output\` regardless of working directory, while caller-supplied relative paths
  resolve against the invocation directory. Invalid inputs, symlinked paths, overlapping input/output
  paths, and unignored in-repository output directories fail explicitly. Base model ID, optional
  revision, LoRA target modules, and end-of-turn token are configurable via `ModelProfile`.

## 2. Why SFT before RFT on historical replies

Reinforcement fine-tuning (RFT) needs a reliable reward signal. On raw Enron reply pairs:

- Median replies are short (~17 words; ~10% are 1–2 word acknowledgments, ~17% exceed 50 words).
- Unreviewed historical replies can reference facts absent from the quoted thread. Optimizing a
  lexical similarity reward with RL encourages guessing unsupported specifics.

Starting with **reply-masked SFT** teaches concise corporate reply structure and tone while keeping
the prompt instruction explicit (*"Draft a reply to the latest message using only the supplied
conversation. Do not invent details. If essential information is missing, ask for it."*).
Reference-token loss measures how closely a model fits the historical reply distribution, **not**
factual correctness on ungrounded cases.

## 3. Dataset hygiene and inferred thread-grouped holdout

`util/data.py` loads `reply-conversations.jsonl` from the configured input directory and:

1. Rejects malformed, empty, exact normalized duplicate, and obvious target-in-conversation rows
   (3,658 of 3,662 exported rows pass on the default Enron dataset).
2. Groups connected rows before splitting using union-find over:
   - conservative normalized subject + participant thread keys from quoted headers,
   - shared substantial quoted blocks (ignoring boilerplate signatures/disclaimers), and
   - substantial replies that reappear inside another row's quoted history.
3. Freezes a seeded group split (`split-42.json` with SHA-256 of the source file) targeting **10%
   final holdout** (366 rows, 10.01%) and **10% of the remainder for validation** (329 rows),
   leaving 2,963 training rows.

Because exported quotes can lack canonical thread IDs, grouping is conservative rather than exact;
never retune hyperparameters on the final holdout.

## 4. Prompt budgeting, reply-only masking, and periodic monitoring

`util/prompts.py`, `util/models.py`, `util/monitoring.py`, and `sft/trainer.py` separate model
identity from hardware limits and instrument live progress:

- **Default base model (`ModelProfile`):** `Qwen/Qwen3-4B-Instruct-2507` (with optional `--revision`
  defaulting to `None`), LoRA rank 8 (`alpha=16`) on `q_proj`, `k_proj`, `v_proj`, `o_proj`.
- **12 GB preset (`Hardware`):** 4-bit quantization, BF16 compute, Unsloth gradient checkpointing,
  batch size 1, gradient accumulation 8, 2,048 max sequence tokens with 384 reserved for completion.
- **Newest-first prompt truncation:** conversations place the newest message at the top. Prompt
  truncation preserves the prefix (latest request first) using only the input budget—never peeking
  at reference reply length.
- **Reply-only supervision:** system/user tokens are masked with `-100`; only assistant reply tokens
  and the end-of-turn token contribute to training, validation checkpoint selection, and held-out
  reference loss. Over-budget training targets are skipped and counted.
- **Periodic validation & headless visualizations:** `--eval-steps` evaluates validation loss across
  intermediate optimizer steps (plus the final step) rather than only at epoch end, flushing
  numeric-only step and validation telemetry to `<run-dir>\metrics.jsonl` and rendering headless
  `loss.png` and `training_metrics.png` figures.
- **Portable evaluation:** after training, the base model is freed and the best validation
  checkpoint is reloaded as a standard `peft.PeftModel` verified against `experiment-base.json`.

## 5. Immutable stage outputs and comparison provenance

Every stage writes into its own access-restricted directory beneath `--output-dir` (default
`output\`):

- **`<output-dir>\baseline\<run-id>\`:** standalone aggregate `summary.json` for the unadapted
  base model (no copied weights, no email text by default, optional `heldout-sample-outputs.txt`
  with `--show-private`).
- **`<output-dir>\sft\<run-id>\`:** `summary.json` (recording `comparison_identity` and linking
  `baseline_run`), `metrics.jsonl`, `loss.png`, `training_metrics.png`, `comparison.png`, and
  `adapter\`.
- **`<output-dir>\grpo\<run-id>\`:** `summary.json` (recording source SFT adapter lineage,
  `comparison_identity`, and baseline/SFT links), `metrics.jsonl`, `training_metrics.png`,
  `comparison.png`, and `adapter\`.

Reusing a saved baseline or SFT summary across runs or across `--output-dir` roots requires an
exact `comparison_identity` match (dataset SHA-256, frozen split digest, held-out line list, base
model ID and optional revision, end-of-turn token, prompt/completion token budget, instruction
digest, and deterministic evaluation decoding). Historical run directories are never overwritten.

## 6. Frozen local model judge and reward boundaries

Historical Enron replies frequently rely on offline context missing from the quoted email. Training
RL against lexical overlap rewards guessing unsupported specifics, while rewarding every question
encourages evasive clarification. `grpo\judge.py` addresses this within clear boundaries:

- **Independent frozen local judge (`JudgeProfile`):** defaults `model_id` to
  `Qwen/Qwen3-4B-Instruct-2507` with optional `revision` (`None` by default; no hosted API
  fallback), defaulting to `cpu` inference (`do_sample=False`) so policy rollouts and reference
  log-probabilities retain the 12 GB GPU budget.
- **Input isolation & untrusted delimiters:** receives only `prompt.conversation` (the exact
  newest-first context shown to the policy) and the candidate reply inside escaped
  `<untrusted_email_conversation>` / `<untrusted_candidate_reply>` delimiters. Neither the archived
  sent reply nor truncated unseen thread text is ever exposed to the judge.
- **Versioned three-dimension rubric (`email-reply-rubric-v1`):** requests integer `0..4` scores for
  `relevance` (answers the request), `grounding` (no invented specifics), and `uncertainty`
  (penalizes both unsupported certainty and unnecessary clarification when the visible conversation
  already supports an answer), aggregated deterministically as `(relevance + grounding +
  uncertainty) / 12.0`.
- **Fail-closed schema & budget checks:** inputs exceeding `max_input_tokens`, truncated outputs,
  malformed JSON, or out-of-range/non-integer fields raise `JudgeBudgetError` / `JudgeFailureError`
  without substituting zero rewards or echoing private email text. Because LLM judges remain
  imperfect proxies rather than ground-truth verifiers, `metrics.jsonl` and `training_metrics.png`
  log each rubric dimension separately to surface reward hacking early.

## 7. Checkpoint-initialized QLoRA GRPO (`grpo\trainer.py`, `grpo\experiment.py`)

`grpo` refines an existing SFT checkpoint rather than starting RL from the unadapted base model:

- **Dual named PEFT adapters on one 4-bit base:** loads the SFT checkpoint as the trainable
  `"default"` policy adapter (`is_trainable=True`) and loads a second frozen copy of the exact same
  SFT checkpoint under `"sft_ref"` (`is_trainable=False`) on the shared NF4 base model. Reference
  log-probabilities explicitly activate `"sft_ref"` via `set_adapter("sft_ref")`—never
  `disable_adapter()`—so KL regularization (`beta > 0`) anchors the policy to the SFT behavior
  rather than reverting toward the unadapted base model.
- **Grouped rollouts & tied-group safety:** samples `group_size >= 2` completions per training
  prompt (`temperature > 0`) over reply tokens only, counts empty or failed generations explicitly,
  and normalizes group-relative advantages when reward std exceeds `1e-8`. Zero-variance (tied)
  groups contribute zero reward advantage without dividing by zero, fabricating differences, or
  recording a false optimizer update; runs that produce zero trainable parameter updates fail
  explicitly rather than claiming a completed GRPO checkpoint.
- **Validation checkpoint selection & 3-stage comparison:** runs deterministic validation every
  `--eval-steps` steps (plus final step) on `validation` prompts only, restores the highest-reward
  validated policy snapshot, exports a portable PEFT `adapter\` + `grpo-lineage.json` without
  touching the source SFT files, and evaluates `baseline`, `sft`, and `grpo` under identical
  `comparison_identity` constraints (`comparison.png` + text-free `summary.json`).

## 8. Scaling to other compatible models

Upgrading to a 7B/8B/14B model on a larger GPU requires no source edits: supply `--model-id` (and
optionally `--revision`), `--target-modules`, and `--end-token` (if different), adjust
`--max-length` / `--batch-size` / `--no-four-bit`, and train a fresh adapter (`check_adapter`
blocks mixing adapters across base models, revisions, or target sets).
