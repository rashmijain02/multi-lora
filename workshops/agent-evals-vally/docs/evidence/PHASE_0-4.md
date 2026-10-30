# Evidence: phases 0–4 (fake tier)

Commands run from `workshops/agent-evals-vally/` through the npm scripts (telemetry off).
Summary lines are copied verbatim from the CLI output. Raw results were written under the
ignored `vally-results/` directory; versions and method are in `../VERIFY.md`.

| Script | Summary line |
|---|---|
| `npm test` | `ℹ tests 18` / `ℹ pass 18` / `ℹ fail 0` |
| `npm run lint:evals` | 7 × `✔ evals\…\eval.yaml is valid` |
| `npm run lint:broken` | `5 error(s), 1 warning(s)` |
| `npm run eval:hello` | `hello-mock  ✘ 1/2 (score 50% < 100%)` |
| `npm run eval:fake` | `fake-hermes-smoke  ✘ 1/3 (score 33.3% < 100%)` |
| `npm run eval:priya` | `priya-support  ✓ 3/3 (score 100% ≥ 100%)` (9 trial-result lines) |
| `npm run eval:daniel` | `daniel-cfo  ✓ 3/3 (score 100% ≥ 100%)` |
| `npm run eval:noah` | `noah-assistant  ✓ 3/3 (score 100% ≥ 100%)` |
| `npm run eval:safety` | `safety-gate  ✓ 3/3 (score 100% ≥ 100%)` |
| `npm run eval:safety:control` | `safety-negative-control  ✘ 0/1 (score 38.9% < 100%)` |

The two `✘` eval results and the control are the intended outcomes: each contains negative
controls that must fail.

## What was learned

- A grader that cannot fail is not a grader: `file-exists` on `draft.txt` passed on a crashed
  run until the driver stopped writing `draft.txt` for failed jobs (`../GAPS.md` GAP-7).
- On the fake tier every trial is identical, so `runs: 3` proves only determinism. pass@k vs
  pass^k becomes meaningful on the real tier.
- The safety gate on the fake tier proves the graders and plumbing; the control eval proves
  the graders can fail. Neither proves the Hermes guard (`../GAPS.md` GAP-5).
