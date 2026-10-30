# Gaps found while building the workshop

A gap is something Vally, Hermes or PersonaDesk could not express, or expressed in a way that
could mislead a learner. Each entry says what we observed and what we did instead. We did
not patch Vally or Hermes for any of them.

## GAP-1: `tool-calls` failure text says "All required tools were called" for a disallowed hit

- **Seen in:** `evals/20-safety/controls`, Vally 0.20.0.
- **Observed evidence string:** `All required tools were called\nThe following disallowed
  tools were called: /^(send_email|…)$/, …` on a grader that had **no** `required` list.
- **Risk:** a reader skimming the first line thinks the grader passed.
- **Workaround:** read the verdict (`passed`) and the second line; the workshop README tells
  learners to do this. Candidate upstream issue.

## GAP-2: `--executor-plugin` paths resolve relative to the eval file

- **Observed:** `--executor-plugin ./vally-hermes-executor` from the workshop folder failed
  with "names '…/evals/01-fake/vally-hermes-executor', which does not exist".
- **Workaround:** install the executor as a local `file:` dev dependency and select it by
  package name. Works from any spec location.

## GAP-3: `type: regression` needs a baseline we do not have

- **Observed:** lint warning `regression-without-baseline`; `defaults.baseline` is checked by
  lint but is not part of the typed `EvalDefaults` in 0.20.0, and we found no documentation
  for its shape.
- **Workaround:** "must never fail" gates are `type: capability` with `threshold: 1.0` and the
  tags `suite: safety, gate: release-blocker`.

## GAP-4: the executor cannot be chosen per stimulus

- **Observed:** `executor` exists only under `defaults`.
- **Consequence:** a negative control that replays a canned trajectory (mock executor) cannot
  sit next to real Hermes stimuli in one file, so it lives in `evals/20-safety/controls/`.

## GAP-5: fake Hermes cannot attempt a blocked or cross-persona action

- **Observed:** `scripts/fake_hermes.py` modes are `ok, no_result, error, nonzero, sleep,
  no_draft, malformed`. None calls a blocked tool or reads another persona's fixture, and
  blocked actions are not Hermes tools at all.
- **Consequence:** on the fake tier the safety eval proves the graders and plumbing, not the
  guard. The control eval proves the graders can fail; the guard itself is tested in
  Workshop 2's own tests and needs the real tier here.

## GAP-6: Hermes `stream-json` has no reasoning or per-turn boundaries

- **Observed (by design in Hermes):** one `result` per one-shot run; no reasoning events.
- **Consequence:** the mapper emits one `turn_start` / `turn_end` pair per run. Turn-scoped
  graders and multi-turn evals wait for phase 6 (`--resume`).

## GAP-7: a failed job can still leave a stored draft

- **Observed:** with `FAKE_HERMES_MODE=nonzero`, the fake stores a draft and then exits 1.
  `run_job` marks the job `failed`, but the draft row exists.
- **What we did:** the driver writes `personadesk-out/draft.txt` only for jobs in
  `awaiting_review`; `job.json` still records the leftover draft for diagnosis, and
  `check-draft.mjs` fails any job that is not `awaiting_review`. Before this change the
  `file-exists` grader in `01-fake` passed on a crashed run.
