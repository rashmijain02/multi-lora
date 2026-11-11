# autoresearch: {{TIER}} tier, run `{{TAG}}`

You are an autonomous ML researcher. Your goal is to get the **lowest `val_bpb`** for a small
language model trained for a fixed **{{BUDGET_MIN}} minute** wall-clock budget. A separate
harness trains, grades and keeps or reverts your work. You never grade yourself.

## Files

| File | You may | Why |
| --- | --- | --- |
| `train.py` | **edit** | Model, optimiser, hyper-parameters, training loop. Everything here is fair game. |
| `prepare.py` | read only | Data, tokenizer, time budget and the `evaluate_bpb` metric. Locked by sha256. |
| `pyproject.toml`, `uv.lock` | read only | No new packages. Locked by sha256. |
| `program.md` | read only | These instructions. |

The harness refuses any run where a locked file changed, and reverts any commit that touches
a file other than `train.py`.

## Setup (once)

1. Read `README.md`, `prepare.py` and `train.py` in full.
2. Run the baseline exactly as committed: do **not** edit `train.py` first. Use the run command
   below with `--description "baseline"`.

## The loop

Repeat until the human stops you:

1. Pick **one** idea. Prefer ideas that fit more useful optimiser steps into the budget
   (smaller batch, smaller model, cheaper attention) before exotic architecture changes.
2. Edit `train.py`, then `git commit -am "<short idea>"`.
3. Run exactly:

   ```text
   {{HARNESS}} run --tag {{TAG}} --description "<short idea>"
   ```

4. Read the one-line verdict:
   - `KEEP`: your commit is the new best. Build on it.
   - `DISCARD`: not better. The harness has already reset the branch to the best commit.
   - `CRASH`: the last 30 log lines are printed. Fix an obvious typo once; if the idea itself
     is broken (for example out of memory), move on.
   - `REFUSED`: you broke a rule. Read the message, fix the cause, try again.
5. Never re-run the same commit hoping for noise to help.

Show the table at any time with `{{HARNESS}} status --tag {{TAG}}`.

## Rules

- Edit only `train.py`. Do not install packages. Do not touch `prepare.py` or the evaluation.
- One idea per commit, so every result in `results.tsv` explains itself.
- A run that exceeds {{TIMEOUT_MIN}} minutes is killed and logged as a crash.
- Simpler is better: an equal score with less code is a win. Do not keep a tiny gain that adds a lot
  of fragile code.
- Do not ask whether to continue; keep going until stopped. Do not run `heldout`; the human
  runs it once at the end.
