# Router parity evidence (light tier, RTX 3080)

**Verdict: the router student does not pass parity yet. Keep the hosted controller's check
selection.** Only 1 of 3 independent training runs passes the gate (round 3, gate version 2).

Every number here was measured on this machine and copied from the run files named in each
section. Nothing is estimated. The run folders are git-ignored. To reproduce them, follow
[PLAN.md §7](../../PLAN.md#7-the-router-step-by-step) and the commands below.

## Setup

| Item | Value |
| --- | --- |
| GPU | NVIDIA GeForce RTX 3080, 10 GB, driver 621.01, Windows; shared with the desktop |
| Torch | 2.9.1+cu128; transformers 4.57.6; peft 0.18.1 |
| Student | `Qwen/Qwen2.5-0.5B-Instruct` @ `7ae5576`, LoRA r=16, alpha=32, on q/k/v/o projections |
| Trainable parameters | 2,162,688 of 496,195,456 (0.44%) |
| Training | 600 rows, 2 epochs, batch 8, 150 optimizer steps, lr 2e-4, bf16 autocast |
| Peak GPU memory | 5.54–5.62 GB in every run |
| Prediction | One email at a time, greedy, at most 40 new tokens |
| Gold | 9 PersonaDesk fixtures (labels: `expected.required_checks`) |

Data splits (from `manifest.json` in each round):

| Round (teacher version) | train | val | test (held-out templates and names) | gold |
| --- | ---: | ---: | ---: | ---: |
| 1 (v1) | 600 | 129 | 240 | 9 |
| 2 (v2) | 600 | 133 | 240 | 9 |
| 3 (v3) | 600 | 139 | 240 | 9 |

val is under 150 because rows that duplicate a training row are removed.

## K0 baseline (TF-IDF + logistic regression)

| Round | val exact | test exact | test noise false positives | gold exact |
| --- | ---: | ---: | ---: | ---: |
| 1 | 129/129 | 124/240 (0.517) | 40/40 | 8/9 |
| 2 | 133/133 | 145/240 (0.604) | 38/38 | 8/9 |
| 3 | 139/139 | 135/240 (0.562) | 38/38 | 8/9 |

**Reading it:** K0 is perfect on wording it has seen (val) and fails on new wording (test). It
flags **every** noise email on test. Its recall is 1.000 for every check only because it
over-predicts. The gate fails it on `test.exact_match` and `test.noise_false_positive_rate`.

## Student, round by round

| Round | Gate | Run (seed) | Train time | test exact | test noise FP | gold exact | K0 gold | Failed conditions |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | v1 | 2026 | 85.8 s | 240/240 | 0/40 | 7/9 | 8/9 | `gold.exact_match_minus_baseline` |
| 2 | v1 | 2026 | 370.2 s | 240/240 | 0/38 | 8/9 | 8/9 | none: **passed** |
| 2 | v1 | 2026 (rerun) | 395.9 s | 224/240 | 0/38 | 8/9 | 8/9 | `test.exact_match` (0.933), `test.recall.calendar_conflict` (0.830) |
| 3 | v2 | 2026 | 82.4 s | 238/240 | 0/38 | 7/9 | 8/9 | `gold.exact_match_minus_baseline` |
| 3 | v2 | 2027 | 243.0 s | 240/240 | 0/38 | 8/9 | 8/9 | none: **passed** |
| 3 | v2 | 2028 | 27.4 s | 233/240 | 0/38 | 7/9 | 8/9 | `test.recall.refund_eligibility` (0.722), `gold.exact_match_minus_baseline` |

Every run had `invalid_rate = 0`: every answer was a parseable JSON list. Every run also had
gold recall at or above 0.90.

### Round 1: teacher v1

- Student gold errors:
  - `noah-003`: an event-seating email that asks Noah to *share* flight and hotel details. The
    student added `travel_policy`.
  - `priya-003`: an injected instruction with payment and bank wording, inside a support email
    reporting an error. The student added `refund_eligibility`.
- K0's gold error: `noah-001`, where it added `travel_policy`.

Both student errors are **extra** checks on kinds of email the teacher never produced.

### Round 2: teacher v2 adds two families, written independently of the fixtures

- `event_logistics_info`: an event confirmation that asks for arrival or accommodation details
  but no booking. Label: `calendar_conflict`.
- Extra injected instructions using vendor-payment and refund vocabulary. Labels unchanged.

Result: the first run passed. Only `priya-003` was still wrong.

A **seeded rerun of the same recipe failed**. All 16 test errors were on one held-out template
of `trip_with_meeting`, where the student missed `calendar_conflict`. GPU training is not
bit-for-bit reproducible: the first-10-step mean loss was 0.242 in one run and 0.240 in the other.
So one passing run proved nothing.

### Round 3: gate v2 and teacher v3

- **Gate v2** keeps every threshold and adds `robustness.min_independent_runs = 3`. Every run must
  pass. `gates.json` was re-pinned; this was a methodology change made after the rerun result
  and is recorded here.
- **Teacher v3** applies a rule that does not need any test row: every family has at least three
  *training* phrasings. In v2, `trip_with_meeting` had one. Test templates are unchanged.

Results:
- `trip_with_meeting` generalised better.
- Seed 2028 instead missed `refund_eligibility` on the held-out refund template (5 errors), and it
  dropped `approval_threshold` on gold `daniel-003`.
- `priya-003` stays wrong in **every** student run across all three rounds.

## Latency (one request at a time, RTX 3080)

| Run | test p50 | test p95 |
| --- | ---: | ---: |
| Round 3, seed 2026 | 190.7 ms | 345.1 ms |
| Round 3, seed 2027 | 191.8 ms | 347.1 ms |
| Round 3, seed 2028 | 192.1 ms | 343.2 ms |

Latency depends mostly on output length. A one-check answer such as `["sla_status"]` takes about
160–190 ms; a two-check answer takes about 315–350 ms. This was read from per-row
`latency_ms` in `predictions_gold.jsonl`. K0 runs in well under 1 ms per row but fails the gate.

## Training time is not a stable measurement here

The same 150-step job took 27.4 s, 82.4 s, 85.8 s, 243.0 s, 370.2 s and 395.9 s.

What was checked:
- **Model dtype:** loading with `dtype=` and with `torch_dtype=` both give `torch.bfloat16`. The
  code change between rounds is not the cause.
- **Throttling:** `nvidia-smi` showed no thermal or hardware slowdown at the time of checking.

The GPU drives the desktop and other applications, and the cause was not identified. **Use these
times only as "minutes, not hours" on a 10 GB GPU.** Do not compare runs by speed.

## What this evidence supports

1. **The method works end to end on a 10 GB GPU.** Data, baseline, student, gate and reports
   all run, and the gate rejects candidates for the right reasons.
2. **The student generalises far better than K0.** Across six runs, held-out test exact match
   was 0.933–1.000 for the student and 0.517–0.604 for K0. The student had no noise false
   positives; K0 flagged every noise email.
3. **The student is not reliably as good as K0 on real fixtures.** Two of three round-3 runs
   score 7/9 against K0's 8/9. The persistent failure is `priya-003`, a prompt-injected support
   email.
4. **Gold is now partly contaminated.** Rounds 2 and 3 were designed after looking at gold errors.
   New gold fixtures are needed before any parity claim.
5. **Nine gold rows is a smoke test.** One row moves gold exact match by 11 points.

## Recommended next steps

- Write new gold fixtures, about 5 per persona, without looking at the synthetic templates. This
  is PLAN exercise 2.
- Replace part of the synthetic teacher with real approved hosted-controller sessions (PLAN §10).
  The persistent `priya-003` error is exactly the kind of case real traffic covers better than
  templates.
- On the Spark tier, try a larger student (3–8B). Use Workshop 4's AutoResearch loop with this
  gate as the locked metric to tune the recipe.

## Reproduce

From `workshops/slm-task-models`:

```bash
uv run python -m slm_router data --teacher-version 3   # 1 or 2 reproduce the earlier rounds
uv run python -m slm_router k0
# then three seeds of train + predict, and the gate, as in README.md
```

`--teacher-version 1` and `2` regenerate the round-1 and round-2 data byte for byte; this was
checked by comparing manifest sha256 values. Student training is not bit-identical on GPU (see
round 2), which is why the gate needs three runs.
