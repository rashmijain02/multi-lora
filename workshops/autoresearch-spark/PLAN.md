# Workshop 4: AutoResearch, an agent that runs its own training experiments

In this workshop a Hermes agent runs a small machine-learning research loop on its own:

1. it changes one thing in a training script;
2. it trains for a fixed few minutes;
3. a harness measures the result;
4. the change is kept if the model got better, otherwise it is undone.

Repeat this a hundred times overnight and you get a record of what works on *your* hardware.
Nobody has to babysit it.

The loop is Andrej Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) (MIT).
This workshop adds three things:

- **Two tiers.** A DGX Spark tier, and a light tier for an ordinary 10 GB gaming GPU with toy data.
- **A guard-rail harness** ([`harness/autoresearch_harness.py`](harness/autoresearch_harness.py)).
  The agent proposes and the harness grades, so the agent never marks its own homework.
- **Hermes as the agent**, using the same ideas as Workshop 2: profiles, toolsets, approvals,
  sessions and `/goal`.

Measured light-tier results are in
[docs/evidence/LIGHT_TIER_BASELINE.md](docs/evidence/LIGHT_TIER_BASELINE.md).

## Contents

1. [Who this is for and what you will learn](#1-who-this-is-for-and-what-you-will-learn)
2. [The loop in one picture](#2-the-loop-in-one-picture)
3. [Concepts you need](#3-concepts-you-need)
4. [Choose your tier](#4-choose-your-tier)
5. [Light tier, step by step](#5-light-tier-step-by-step)
6. [Spark tier, step by step](#6-spark-tier-step-by-step)
7. [Run the loop with Hermes](#7-run-the-loop-with-hermes)
8. [Monitor, stop, and test on held-out data](#8-monitor-stop-and-test-on-held-out-data)
9. [Cost of a kept improvement](#9-cost-of-a-kept-improvement)
10. [Part B capstones: point the loop at your own models](#10-part-b-capstones-point-the-loop-at-your-own-models)
11. [How this fits with Workshops 1–3](#11-how-this-fits-with-workshops-13)
12. [What the harness enforces, and what it cannot](#12-what-the-harness-enforces-and-what-it-cannot)
13. [Troubleshooting](#13-troubleshooting)
14. [Exercises and exit criteria](#14-exercises-and-exit-criteria)

---

## 1. Who this is for and what you will learn

You should be comfortable running commands in a terminal and reading a little Python. You do
not need to know how transformers work inside. The agent edits the model, and you learn by
reading its experiments.

By the end you will be able to:

- explain **why a fixed time budget** makes experiments comparable, and why it rewards *more
  steps* on slow hardware;
- explain **why the metric must be locked away from the agent**, and how to detect tampering;
- run an **autonomous keep-or-revert loop** with Hermes, and stop it sensibly;
- check a "best" result against **held-out data** and against **run-to-run noise**;
- put a **cost** on each improvement and compare it with the Workshop 2 cost model.

## 2. The loop in one picture

```text
           +-------------------------- you (human) -------------------------+
           |  choose tier, run `init` once, start Hermes, read results,     |
           |  run `heldout` at the end                                      |
           +---------------------------------------------------------------+
                                     |
                                     v
 +------------------+   edit + commit   +---------------------------------------------+
 |  Hermes agent    | ----------------> |  harness `run`                              |
 |  (profile:       |                   |  1. sha256 lock check on prepare.py & deps  |
 |   autoresearch)  |                   |  2. only train.py changed since best?       |
 |                  | <---------------- |  3. train for the fixed budget (+ timeout)  |
 |  reads verdict,  |  KEEP / DISCARD / |  4. parse val_bpb from the summary          |
 |  picks next idea |  CRASH / REFUSED  |  5. better? keep commit : git reset to best |
 +------------------+                   |  6. append a row to results.tsv             |
                                        +---------------------------------------------+
```

The agent only ever gets a verdict. It cannot write `results.tsv` or move the "best" pointer, and
it cannot change how the score is computed.

## 3. Concepts you need

**val_bpb (validation bits per byte).** How many bits the model needs, on average, to predict
each byte of text it has not trained on. Lower is better. It is measured per *byte*, not per
token, so changing the tokenizer cannot fake an improvement. The function is `evaluate_bpb` in
`prepare.py`.

**Fixed wall-clock budget.** Every experiment trains for exactly the same number of seconds:
120 on the light tier, 300 on the Spark. A bigger model is not "free". It must beat a
smaller model that got more steps in the same time. This is why the best settings differ by
hardware:

- an H100 rewards big models;
- a GB10 or an RTX 3080 rewards small batches and small models.

**Steps.** One optimiser update. On slow hardware the loop is usually *step-limited*: more,
smaller updates beat fewer, larger ones. Our 3080 baseline confirms this. Halving the batch
doubled the steps and improved val_bpb.

**Hill climbing (keep or revert).** Try one change and keep it only if the score improves. It is
simple and greedy. It can get stuck, but it never gets worse. This is the same loop as
Workshop 2's [hill climbing](../personal-agent-multilora/docs/SIMULATED_CORP_GUIDE.md), except
that here the "policy" being improved is training code.

**Locked metric (Goodhart's law).** "When a measure becomes a target, it ceases to be a good
measure." An agent rewarded for a lower number may find that editing the evaluation is the
easiest way to get one. So `prepare.py` (data, tokenizer, evaluation, time budget),
`pyproject.toml` and `uv.lock` are:

- marked read-only;
- hashed with sha256 at `init`.

Any later change makes the harness refuse to run. Workshop 2 has the same principle: the
deterministic [`score_round.py`](../personal-agent-multilora/scripts/score_round.py) grades the
assistants, not the assistants themselves.

**Held-out test.** After about 100 experiments chosen by the validation score, the "best" result
is partly luck: you picked the run that happened to suit those validation documents. The
upstream data already sets aside documents 0–10,000 as a `test` split that the loop never uses.
At the end, `heldout` retrains the baseline and the best commit and scores both on that split.

**Noise.** Two runs of the same code do not give exactly the same val_bpb. A "gain" smaller than
the noise is not a gain. You measure the noise in [exercise 2](#14-exercises-and-exit-criteria)
and then set `--min-delta` to require a real margin.

## 4. Choose your tier

| | **Light tier** | **Spark tier** |
| --- | --- | --- |
| For | Learners without a Spark | Learners with an NVIDIA DGX Spark |
| Hardware | NVIDIA Ampere or newer, at least 10 GB (tested: RTX 3080 10 GB, Windows) | DGX Spark, GB10 Blackwell (sm_121), 128 GB unified memory |
| Training code | [`jsegov/autoresearch-win-rtx`](https://github.com/jsegov/autoresearch-win-rtx) (MIT; native Windows; SDPA attention; built-in VRAM autotune) | Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) with the Blackwell changes in §6 |
| Data | TinyStories (642 MB download) | TinyStories (light settings) or upstream's default |
| Budget per run | **120 s** | **300 s** |
| Context length | 512 | upstream (2048) |
| Eval tokens | 4 × 524,288 | upstream (40 × 524,288) |
| Starting `train.py` | depth 4, total batch 2^16, full attention | depth 4, total batch 2^17 |
| Harness timeout | 900 s (first run includes autotune) | 1,500 s |
| Wall time per run | 129–137 s, measured | about 5.5 min (budget plus eval) |
| Runs per hour (GPU) | about 25, measured | about 10 |
| Measured here? | **Yes**: [baseline evidence](docs/evidence/LIGHT_TIER_BASELINE.md) | **No**: community report only; verify on your Spark |

**Scores are not comparable across tiers.** Budget, context length and evaluation size all
differ. Compare only within one tier on one machine.

All tier constants live in one place: `TIERS` at the top of
[`harness/autoresearch_harness.py`](harness/autoresearch_harness.py).

## 5. Light tier, step by step

All commands start in `workshops/autoresearch-spark`. They are shown for PowerShell; on Linux
use `export VAR=value` instead of `$env:VAR = "value"`.

### 5.1 Prerequisites

- An NVIDIA driver recent enough for CUDA 12.8. Check with `nvidia-smi`.
- [uv](https://docs.astral.sh/uv/) and git on `PATH`.
- About 4 GB free disk: the training environment, plus 642 MB of data and the tokenizer.

### 5.2 Get the training code (once)

The third-party code is **cloned, not copied** into this repository. `upstream/` is git-ignored.

```powershell
git clone https://github.com/jsegov/autoresearch-win-rtx.git upstream/autoresearch-win-rtx
git -C upstream/autoresearch-win-rtx checkout a4123c6   # the commit measured in the evidence
```

Before running third-party code, read its `prepare.py`. Note what it downloads (one
TinyStories parquet from Hugging Face) and where it writes (the cache directory below).

### 5.3 Install, download and smoke-test (once)

Keep the dataset cache inside the ignored folder so nothing lands in your home directory:

```powershell
$env:AUTORESEARCH_CACHE_DIR = "$PWD/upstream/cache"
cd upstream/autoresearch-win-rtx
uv sync                        # about 80 s; PyTorch 2.9.1 + CUDA 12.8
uv run prepare.py              # about 40 s; TinyStories + BPE tokenizer
uv run train.py --smoke-test   # about 3 min; ends with a "---" summary and val_bpb
Remove-Item checkpoint_pre_eval.pt
cd ../..
```

The smoke test also runs the GPU autotune once and caches the result, so later runs start faster.

### 5.4 Lock the metric and set the tier (once per run tag)

```powershell
uv run --no-project python harness/autoresearch_harness.py init `
    --upstream upstream/autoresearch-win-rtx --tier light --tag light-<yourdate>
```

What `init` does, so you can explain it:

1. Creates the branch `autoresearch/<tag>` in the clone.
2. Writes the light-tier constants into `prepare.py` and the starting point into `train.py`.
3. Writes a filled-in [`program.md`](program.md): the agent's instructions, with the exact
   harness command.
4. Commits that setup, records the sha256 of `prepare.py`, `pyproject.toml` and `uv.lock`, and
   makes `prepare.py` read-only. Windows has no `chmod a-w`; read-only plus a hash check works
   on every OS.
5. Saves `runs/<tag>/state.json` (git-ignored). It also records `AUTORESEARCH_CACHE_DIR`, so
   runs find the data even from a shell that never set it.

### 5.5 Run the baseline yourself (recommended)

Run the baseline yourself, then compare it with the
[evidence](docs/evidence/LIGHT_TIER_BASELINE.md) before you hand over to the agent:

```powershell
uv run --no-project python harness/autoresearch_harness.py run --tag light-<yourdate> `
    --description "baseline"
```

Expect `KEEP: val_bpb=0.53…`, about 1.2 GB peak memory and about 480 steps. If you are far off,
check [troubleshooting](#13-troubleshooting) before going further.

## 6. Spark tier, step by step

> **Status: not yet measured in this repository.** The steps below follow upstream's
> instructions and one public community report, `schaferk/autoresearch-blackwell-gb10`: a
> single-author write-up of 151 experiments on a GB10. Treat every Spark-specific detail as
> **verify on your Spark**. Record what you find in a `docs/evidence/SPARK_TIER_BASELINE.md`.

### 6.1 Differences from the H100 setup

The community report made these changes to upstream for GB10 (sm_121):

| Upstream (H100) | GB10 change | Why |
| --- | --- | --- |
| FlashAttention 3 | PyTorch `scaled_dot_product_attention` (SDPA) | The report says FA3 does not support sm_121 |
| PyTorch `cu128` index | `cu130` index | Matches CUDA 13.0 on the system; confirm with `nvidia-smi` |
| `kernels` dependency | removed | Only needed for FA3 |
| H100 peak FLOPS (989.5 TFLOPS) | GB10 BF16 peak (the report uses 213 TFLOPS) | Only affects the printed MFU, not val_bpb |
| Sliding-window attention | lost with SDPA | Use `WINDOW_PATTERN = "L"` |

The Spark CPU is ARM (aarch64). Check that `uv sync` installs a CUDA-enabled aarch64 PyTorch
wheel. If `torch.cuda.is_available()` is `False` after install, the wheel is CPU-only; fix the
index before continuing.

### 6.2 Commands (bash, on the Spark)

```bash
git clone https://github.com/karpathy/autoresearch.git upstream/autoresearch
# Make the section 6.1 changes on a commit of your own and note its hash.
export AUTORESEARCH_CACHE_DIR="$PWD/upstream/cache"
(cd upstream/autoresearch && uv sync && uv run prepare.py)
uv run --no-project python harness/autoresearch_harness.py init \
    --upstream upstream/autoresearch --tier spark --tag spark-<yourdate>
uv run --no-project python harness/autoresearch_harness.py run --tag spark-<yourdate> \
    --description "baseline"
```

For a quick first pass, you can use the light-tier data settings on the Spark too: `--tier light`
with a 300-second budget, set via `TIERS`. That lets you compare "same data and settings, more
hardware" against the 3080.

### 6.3 What to expect (community report, not ours)

The report starts from upstream's depth 8 and batch 2^19. It records:

- baseline val_bpb 1.463 with 44 GB peak memory and 93 steps per run;
- after 151 experiments, best val_bpb 1.135 with 6.1 GB, depth 4 and about 1,300 steps.

About 91% of the gain came from cutting the batch size. Our Spark tier starts at depth 4 and
batch 2^17, as your original plan suggested. The agent therefore skips the most obvious
discovery and has to find the subtler ones.

## 7. Run the loop with Hermes

The kickoff in the original plan used Claude Code. This workshop uses **Hermes**, so that agents
are run the same way across all the workshops.

### 7.1 A dedicated profile (once)

A Hermes **profile** is an isolated agent: its own config, memory, sessions and credentials.
Workshop 2 gives each persona one. Give the researcher its own too, so its long-running
permissions never mix with your other agents:

```powershell
hermes profile create autoresearch
hermes -p autoresearch config set terminal.timeout 1000    # Spark: 1600
hermes -p autoresearch config set goals.max_turns 60
```

Why these two settings:

- **`terminal.timeout`**: Hermes kills any terminal command after 180 s by default. One harness
  run takes about 135 s on the light tier (over 3 min the first time) and over 5 min on the
  Spark. Without this change, every run is killed halfway through.
- **`goals.max_turns`**: the turn budget for `/goal` (below). It is your stop-loss.

Set the model provider the same way as in
[Workshop 2's user guide](../personal-agent-multilora/docs/USER_GUIDE.md).

### 7.2 Start an interactive session in the clone

```powershell
hermes -p autoresearch chat --in upstream/autoresearch-win-rtx -t terminal,file --checkpoints
```

| Flag | Hermes concept | Why here |
| --- | --- | --- |
| `-p autoresearch` | profile | Isolated memory, config and credentials |
| `--in <dir>` | session workspace | The agent works in the clone, not in this repository |
| `-t terminal,file` | toolsets | Only shell and file tools. No web: the agent cannot download "better" code |
| `--checkpoints` | filesystem checkpoints | A rollback point before destructive file changes |

Keep **approvals on**: do not pass `--yolo`. The loop needs no dangerous commands. The harness,
not the agent, runs `git reset --hard`. An approval prompt therefore means the agent is doing
something unexpected, and you want to see it.

Use an **interactive** session, not a one-shot `-q --oneshot` call. A one-shot call answers and
exits; the loop has to keep its context across dozens of experiments. If you close the window,
resume with `hermes -p autoresearch chat --resume latest --in upstream/autoresearch-win-rtx`.

### 7.3 Kick off with `/goal`

First, a normal message:

> Read program.md, README.md, prepare.py and train.py. Then run the setup: the baseline is already
> recorded, so confirm `status` shows it, and tell me your first three ideas.

Check that the ideas are sensible, then hand over:

```text
/goal Follow program.md: run the autoresearch loop for tag light-<yourdate>, one idea per
commit, always through the harness run command, until val_bpb has not improved for 10
consecutive runs. Then print the harness status table and stop.
```

`/goal` is Hermes's standing objective. After every turn a small **judge** model checks whether
the goal is met. If not, Hermes continues by itself, until the goal is done, you
`/goal pause`, or the turn budget runs out.

Note the two different judges:

| Judge | Decides | Can the agent influence it? |
| --- | --- | --- |
| Hermes goal judge | "Is the agent finished?" | Yes, through what it says. That is why the turn budget is the backstop |
| The harness | "Did val_bpb improve?" | No. Locked files, fixed budget, a separate process |

## 8. Monitor, stop, and test on held-out data

**Watch** from a second terminal (in `workshops/autoresearch-spark`):

```powershell
uv run --no-project python harness/autoresearch_harness.py status --tag light-<yourdate>
nvidia-smi
```

In Hermes, `/goal status` shows turns used.

**Healthy signs:**
- mostly `discard` rows with an occasional `keep`;
- descriptions that each name one idea;
- wall time per run steady.

**Warning signs:**
- `REFUSED` repeating (the agent is fighting the rules);
- many `crash` rows in a row (it is stuck on out-of-memory errors);
- the same idea retried with tiny variations.

**Stop** when either:
- 10 consecutive runs bring no improvement (the goal above); or
- you hit your time or turn budget. Use `/goal pause`, then close the session.

**Then run the held-out test once:**

```powershell
uv run --no-project python harness/autoresearch_harness.py heldout --tag light-<yourdate>
```

This retrains the baseline and best commits in throwaway git worktrees. Each worktree's copy of
`prepare.py` evaluates on the `test` split instead of `val`. The result is written to
`runs/<tag>/heldout.tsv`.

Report the gain **on test**, not on val. If the test gain is much smaller than the val gain, the
loop overfitted to the validation documents. That is a finding, not a failure.

## 9. Cost of a kept improvement

Each kept row has a price. Find it like this:

```text
cost per kept improvement = (agent token cost + GPU energy cost) for the whole session
                            ---------------------------------------------------------
                                      number of "keep" rows after the baseline
```

- **Agent tokens:** read them from your provider's usage page for the session's time window. Use
  the per-model prices in Workshop 2's [cost model](../personal-agent-multilora/docs/COST_MODEL.md),
  which lists Copilot and Foundry prices separately.
- **GPU energy:** wall hours × average board power (from `nvidia-smi --query-gpu=power.draw
  --format=csv -l 60`) × your electricity price.
- Compare: hosted frontier model plus local GPU, versus a small local model driving the loop on
  the Spark. That is the same trade-off as COST_MODEL §8.

The light-tier evidence does not include agent costs yet, because runs 2–3 were made by hand.
Record your own in your evidence file. Do not copy anyone else's.

## 10. Part B capstones: point the loop at your own models

Part A optimises a toy language model. Part B reuses the **same harness ideas** on training you
actually care about. Only the locked file and the summary line change.

| | **Part B (Spark)** | **Part B-lite (light tier)** |
| --- | --- | --- |
| What the agent edits | Workshop 3's small-model training recipe (hyper-parameters and data mix) | Workshop 1's 0.5B LoRA recipe (rank, alpha, learning rate, epochs, target modules) |
| Locked metric | Workshop 2's [`score_round.py`](../personal-agent-multilora/scripts/score_round.py) pass rate on a fixed scenario set | Workshop 1's existing evaluation on its held-out split |
| Fixed budget | Same GPU minutes per trial | Same GPU minutes per trial (fits in 10 GB) |
| Held-out | A scenario set the loop never sees | The test split of the email dataset |

To adapt the harness:

1. List the metric files in `LOCKED_FILES`.
2. List the recipe file in `EDITABLE_FILES`.
3. Make the training command print a `---` block with `val_bpb:` (or rename the key) in
   `parse_summary`.

Everything else stays the same: one idea per commit, keep or revert, refusal on tampering, and
the held-out score at the end.

## 11. How this fits with Workshops 1–3

| Workshop | Produces | Used here |
| --- | --- | --- |
| 1. Email Multi-LoRA | Persona and classification LoRA adapters, plus an evaluation | Part B-lite optimises its LoRA recipe |
| 2. PersonaDesk on Hermes | Hermes profiles and approvals, a deterministic scorer, hill climbing, a cost model | The same Hermes concepts; the same "agent never grades itself"; a cost line per improvement |
| 3. Small task models ([`slm-task-models`](../slm-task-models/PLAN.md)) | A router student behind a hash-locked parity gate; judge and controller planned | Part B optimises its training recipe under a locked parity metric |
| **4. AutoResearch (this one)** | A method for letting an agent tune training safely | Can run under Workshop 3 to find better small-model recipes |

## 12. What the harness enforces, and what it cannot

| Rule | Enforced by | Test |
| --- | --- | --- |
| Metric, data and dependencies unchanged | sha256 of `prepare.py`, `pyproject.toml`, `uv.lock` checked before every run | `test_tampered_metric_is_refused` |
| Only `train.py` changes | `git diff --name-only <best>..HEAD`; anything else is reverted | `test_edit_outside_train_py_is_reverted` |
| Keep only real improvements | Harness compares with the stored best (optionally by `--min-delta`) | `test_keep_then_discard_resets_to_best` |
| Crashes and out-of-memory runs logged, not hidden | No summary block means `crash`; OOM tagged in the description | `test_crash_is_logged_with_reason_and_reverted` |
| No re-rolling the same commit for luck | Running the best commit again is refused | `test_rerunning_best_commit_is_refused` |
| Hung runs end | Timeout per run kills the whole process tree (`uv` and its Python child) | `test_hung_run_and_its_child_are_killed` |
| Final score on unseen data | `heldout` swaps the val range for the test range in a throwaway copy | `test_heldout_scores_on_test_split` |

**Limits, said plainly.** The agent has a shell. A determined agent could edit the harness
itself, `state.json`, or the hashes. Three things narrow this:

- the harness and state live **outside** the clone the agent works in;
- the profile has no web access;
- approvals stay on.

Two things detect it:

- the git history of this repository shows any harness edit;
- `heldout` re-trains from commits, so a faked `results.tsv` would not survive it.

This is a teaching harness, not a sandbox. For stronger isolation, use Hermes's Docker terminal
backend (`hermes -p autoresearch config set terminal.backend docker`) with only the clone
mounted.

Run the harness tests (from `workshops/autoresearch-spark`):

```powershell
uv run --group dev pytest -q
uv run --group dev ruff check .
```

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Every Hermes run stops after 3 minutes | Hermes terminal timeout (180 s default) | `hermes -p autoresearch config set terminal.timeout 1000` (Spark: 1600), then restart the session |
| `REFUSED: locked files changed` | `prepare.py`, `pyproject.toml` or `uv.lock` edited, or `uv` rewrote the lock | `git -C <clone> checkout <best> -- <file>`; never `uv add` during a run |
| `REFUSED: commit your train.py change first` | Uncommitted edits | `git commit -am "<idea>"` in the clone, then run again |
| `error: upstream has uncommitted changes` on `init` | Leftover files from experimenting | Commit or remove them; `uv.lock` and `checkpoint_pre_eval.pt` are allowed |
| `CRASH` with `[OOM]` | Model or batch too big | Expected sometimes; the harness already reverted. On 10 GB keep total batch at 2^16 or below at depth 4 or more |
| `CRASH`, log says TinyStories parquet not found | Cache directory differs between `prepare.py` and the run | Set `AUTORESEARCH_CACHE_DIR` the same way before `prepare.py` and `init` (init records it) |
| `torch.cuda.is_available()` is `False` | CPU-only wheel (common on the Spark's aarch64) or an old driver | Check `nvidia-smi`; on the Spark use the CUDA 13 index (§6.1) |
| Wall time per run creeping up | Thermal throttling or another GPU job | `nvidia-smi`; close other GPU apps; compare the `steps` column across runs |
| `REFUSED: nothing new to test` | Ran without a new commit | Make a change and commit it first |

## 14. Exercises and exit criteria

1. **Reproduce the baseline** (§5.5). Your val_bpb should be within about 0.01 of the evidence.
2. **Measure noise.** Re-run the baseline commit twice on a scratch tag:
   - `init` a new tag;
   - run `baseline`;
   - make a whitespace-only commit to `train.py` and run it.

   The spread between the two is your noise floor. Use it as `--min-delta` for the real session.
3. **First agent session.** Run Hermes for at least 15 experiments. In your own words, explain
   the first three `keep` rows.
4. **Held-out check.** Run `heldout`. Is the test gain at least half the val gain?
5. **Cost line.** Fill in §9 for your session.
6. **Spark tier only.** Write `docs/evidence/SPARK_TIER_BASELINE.md` with the measured version of
   the §4 table's Spark column.

You are done when you can explain to someone else:
- why the agent may not touch `prepare.py`;
- why the light tier starts with a small model;
- what the held-out test told you about your session's "best".

---

Credits: the loop and training code are by Andrej Karpathy ([autoresearch](https://github.com/karpathy/autoresearch),
MIT). The Windows RTX port is by jsegov ([autoresearch-win-rtx](https://github.com/jsegov/autoresearch-win-rtx),
MIT). The GB10 observations come from `schaferk/autoresearch-blackwell-gb10`. None of their
code is copied into this repository; the clones stay in the git-ignored `upstream/` folder.
