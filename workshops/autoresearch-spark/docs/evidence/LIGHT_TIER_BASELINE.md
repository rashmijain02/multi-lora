# Light tier baseline: measured on an RTX 3080

This report records the first light-tier run of the AutoResearch workshop. It proves three things
before any learner tries the loop:

1. the Windows RTX fork trains and evaluates on a 10 GB consumer GPU;
2. the harness keeps an improvement, reverts a regression, and resets the branch on its own;
3. the held-out test agrees with the validation result.

Every number below is copied from the harness's `results.tsv`, `heldout.tsv` and run logs, which
are under `workshops/autoresearch-spark/runs/light-3080/` on the machine that ran them. That
folder is git-ignored. Nothing here is estimated.

## Setup

| Item | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 3080, 10 GB (compute 8.6), driver 621.01 |
| OS | Windows, native (no WSL) |
| Training code | [`jsegov/autoresearch-win-rtx`](https://github.com/jsegov/autoresearch-win-rtx) at commit `a4123c6` (MIT), cloned to `workshops/autoresearch-spark/upstream/` |
| PyTorch | 2.9.1+cu128, BF16 supported, SDPA attention, no `torch.compile` |
| Data | TinyStories GPT-4 clean (642 MB parquet), BPE vocabulary 8192, trained in 23 s |
| One-off cost | `uv sync` 80 s; `prepare.py` 37 s; smoke test 3 min 18 s, including the first GPU autotune |

The harness `init --tier light` applied these settings:

| File | Constant | Upstream | Light tier |
| --- | --- | --- | --- |
| `prepare.py` (locked) | `TIME_BUDGET` | 300 | **120** seconds |
| `prepare.py` (locked) | `MAX_SEQ_LEN` | 2048 | **512** |
| `prepare.py` (locked) | `EVAL_TOKENS` | 40 × 524288 | **4 × 524288** |
| `train.py` (start) | `DEPTH` | 8 | **4** |
| `train.py` (start) | `TOTAL_BATCH_SIZE` | 2^19 | **2^16** |
| `train.py` (start) | `WINDOW_PATTERN` | `"SSSL"` | **`"L"`** |

Why start smaller: the upstream configuration took about 9.8 s per optimiser step in the smoke
test, so a 2-minute budget would allow only about 12 steps. The light-tier start gets 483.

## Results

`results.tsv` (`training_s` is the fixed budget; wall time per run was 129–137 s):

| # | Commit | val_bpb | Peak memory | Steps | Params | Status | Change |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `0b86912` | 0.533969 | 1.2 GB | 483 | 11.5M | keep | baseline (light start) |
| 2 | `3ced217` | **0.527007** | 1.2 GB | 937 | 11.5M | keep | halve total batch 2^16 → 2^15 |
| 3 | `26be7d8` | 0.536203 | 1.4 GB | 492 | 26.3M | discard | depth 4 → 6 |

The harness reset the branch to `3ced217` after run 3 without being asked. Runs 2 and 3 were
made by hand to test the mechanics; they are not an agent session.

Held-out test (`heldout.tsv`): both commits were retrained in throwaway git worktrees whose copy
of `prepare.py` evaluates on documents 0–10,000. The loop never sees those documents.

| Label | Commit | val_bpb (loop) | test_bpb (held out) |
| --- | --- | --- | --- |
| baseline | `0b86912` | 0.533969 | 0.537513 |
| best | `3ced217` | 0.527007 | 0.532005 |
| **gain** | | **0.006962** | **0.005508** |

## What this shows

- **This GPU is step-limited, not memory-limited.** Peak memory was 1.2 GB of 10 GB. Halving
  the batch doubled the steps (483 → 937) and won. A deeper model (26.3M parameters) had
  fewer useful steps and lost. The 151-experiment GB10 community report reached the same
  conclusion on a DGX Spark (see the Spark tier in [PLAN.md](../../PLAN.md)).
- **The gain survived the held-out test**, losing about a fifth of its size (0.0070 → 0.0055).
  Expect some shrinkage: whatever you select on validation is slightly flattered by it.
- **Noise is not yet measured.** Each row is one training run. Before trusting gains under
  about 0.003, run the same commit twice (a deliberate exercise in the plan) and set
  `--min-delta` to roughly that spread.
- The autotune chose device batch 16 with activation checkpointing **on**, despite the free
  memory. Turning it off is an obvious first idea for an agent.

## Reproduce

Start in `workshops/autoresearch-spark` and follow the light-tier steps in
[PLAN.md](../../PLAN.md#5-light-tier-step-by-step). Use a new `--tag`. Your numbers will differ
slightly; compare only within your own tier and machine.
