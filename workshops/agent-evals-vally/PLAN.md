# Workshop 6 plan: Evaluating Hermes agents with Vally

Status: **plan only — nothing in this document is built or measured yet.** Every score,
token count, and cost in this workshop must come from a run recorded in `docs/evidence/`;
none appear here.

Workshops 2–5 each grew their own checks: PersonaDesk review records, the Workshop 3
parity gate, the Workshop 4 locked metric. This workshop gives all of them one shared,
repeatable evaluation harness: **[Vally](https://microsoft.github.io/vally/)**, Microsoft's
open-source (MIT) eval platform for AI agents. You will write `eval.yaml` specs, build a
small **Hermes executor** so Vally can drive Hermes, and turn PersonaDesk's safety rules
into evals that run in seconds on a laptop and with real models when you choose.

It builds on:

- **Workshop 2 (PersonaDesk)** — profiles `pd-priya`, `pd-daniel`, `pd-noah`, the
  `personadesk` toolset, the `pre_tool_call` guard, fixtures, and the deterministic
  `scripts/fake_hermes.py` ([`../personal-agent-multilora/`](../personal-agent-multilora/)).
- **Workshop 3 (small task models)** — the router student and its parity gate
  ([`../slm-task-models/`](../slm-task-models/)).
- **Workshop 5 (PersonaDesk Portal)** — per-persona agents that will need a release gate
  ([`../persona-portal/PLAN.md`](../persona-portal/PLAN.md)).
- **The Hermes source** at [`../../external/hermes-agent`](../../external/hermes-agent),
  especially `hermes_cli/stream_json.py` (the event protocol this workshop consumes).

Primary Vally reading:
[Writing eval specs](https://microsoft.github.io/vally/guides/writing-eval-specs/),
[eval spec reference](https://microsoft.github.io/vally/reference/eval-spec/),
[grader catalog](https://microsoft.github.io/vally/reference/graders/),
[writing custom executors](https://microsoft.github.io/vally/guides/writing-custom-executors/).

---

## 1. What you will learn

1. The Vally pipeline: **stimulus → executor → trajectory → graders → score**.
2. How to write an `eval.yaml`: stimuli, graders, environments, constraints, scoring.
3. Why *how* an agent worked (its trajectory: tool calls, tokens, turns) matters as much
   as *what* it answered, and how to grade both.
4. How to keep answer keys **hidden from the agent** with `grading_environment`.
5. How to build a **custom executor** that adapts another agent's event stream (Hermes
   `stream-json`) into Vally's trajectory format.
6. How to read **pass@k** and **pass^k**, and why a single green run proves little.
7. How to use an **LLM judge** without letting the agent grade itself.
8. How to compare two configurations (hosted vs local writer, Workshop 3 router on/off)
   with `vally compare`.

---

## 2. Key decision: Vally grades, Hermes runs — through our own executor

Vally ships one real agent executor, `copilot-sdk`, plus a `mock` executor for testing
graders. `copilot-sdk` runs **GitHub Copilot's** agent; pointing it at PersonaDesk would
evaluate Copilot, not our Hermes profiles, plugin, and guard. That breaks the repository
rule that Hermes is the only agent framework.

So the workshop builds **`vally-hermes-executor`**, a small plain-JavaScript (ES module, no
build step) plugin loaded with `vally eval --executor-plugin vally-hermes-executor`. It does
not spawn Hermes directly. It runs `scripts/run_personadesk_job.py`, which creates a real
PersonaDesk job and calls the production `run_job` (lock, job-token binding, stored draft).
`run_job` then runs exactly the command PersonaDesk already uses
(`hermes_plugin/tasks.py` `build_worker_argv`), through a small tee
(`scripts/tee_hermes.py`) that keeps a copy of the stream and enforces the time limit:

```text
hermes -p <profile> chat --oneshot --query-file <file> --format stream-json \
       --toolsets personadesk --max-turns <n>
```

and translates each JSONL line into a Vally trajectory event:

| Hermes `stream-json` event (`hermes_cli/stream_json.py`) | Vally trajectory event |
|---|---|
| `system` / `init` (`model`, `session_id`) | `metadata.model`, `metadata.sessionID` |
| `text` deltas (concatenated) | one `assistant_message`; also `Trajectory.output` |
| `tool_use` (`name`, `tool_call_id`, `input`) | `tool_call` (`toolName`, `toolCallId`, `arguments`) |
| `tool_result` (`output`, `is_error`, `duration_ms`) | `tool_result` (`success = !is_error`, `result` or `error`) |
| `result.tokens` (`input`, `output`, `cache_read`, `cache_write`) | `token_usage` |
| `result.exit_code ≠ 0` or `result.error` | `error` |
| Process killed at the time limit | partial trajectory, `endReason: "agent_timeout"` |

Why this is a good learning shape:

- **No Hermes changes.** We consume a public, documented protocol. Nothing in
  `external/hermes-agent` is edited.
- **The grader stays outside the agent.** Hermes produces a trajectory; Vally, a separate
  process, scores it. That is the "an agent never grades itself" rule, enforced by
  architecture rather than by convention.
- **Same stream, two agents.** `scripts/fake_hermes.py` already emits the same protocol, so
  the whole harness runs with **no model and no GPU** before anyone spends a token.

If the mapping can't express something (for example, Hermes reasoning events, which
`stream-json` deliberately omits), log it in `docs/GAPS.md`. Do not reach into Hermes
internals to get it.

---

## 3. Vally concepts, mapped to this repository

| Vally concept | Meaning | PersonaDesk example |
|---|---|---|
| **Stimulus** | One test case: a `prompt` (or multi-turn `turns`) plus graders | "Draft a reply to fixture `priya-002`" |
| **Executor** | Runs the agent and returns a trajectory | `hermes` (ours), `mock` (grader tests) |
| **Trajectory** | Ordered events: messages, tool calls/results, tokens, errors | One `pd-priya` job |
| **Grader** | Scores one aspect of a trajectory | `tool-calls`: `pd_draft_reply` required |
| **`agent_environment`** | Files/skills/commands the agent *may* see | The fixture being answered |
| **`grading_environment`** | Files only graders see (answer keys) | Expected classification, banned phrases |
| **Constraints** | Hard limits per trial | `max_turns`, `max_tokens`, `max_duration` |
| **Scoring** | Weighted average of grader types, plus a threshold | Safety graders weigh most |
| **`runs` / pass@k / pass^k** | Repeat trials; "passed at least once" vs "passed every time" | Safety evals demand pass^k |
| **`type: capability` vs `regression`** | "Can it do this?" vs "Is it still as good as a baseline?" (Vally's lint expects `defaults.baseline` for `regression`) | Persona evals and the safety gate are both `capability`; a gate is a threshold of 1.0, not an eval type |
| **`vally compare`** | Judge baseline vs treatment against a rubric | Hosted writer vs local LoRA writer |

### Choosing graders: cheapest first

Vally labels every grader by cost and determinism. The workshop rule: **use a static
grader whenever one can decide the question; use an LLM judge only for what static graders
cannot judge (tone, helpfulness).**

| Question | Grader | Cost |
|---|---|---|
| Did the run finish cleanly? | `completed`, `error-count` | free |
| Did it call `pd_draft_reply`, after reading the fixture? | `tool-calls` (`required`, `sequence`, `min_count`) | free/low |
| Did it avoid blocked actions (send, delete, forward)? | `tool-calls` (disallowed) | low |
| Did the stored draft avoid a secret or another persona's data? | `output-not-contains`, `transcript-not-contains`, `program` | free/low |
| Did it stay in budget? | `constraints` (`max_turns`, `max_tokens`, `max_duration`) | free |
| Did it loop? | `max-repeat`, `loop-outcome` | free |
| Is the reply in the persona's voice and helpful? | `prompt` (rubric), later `panel` | high |

---

## 4. Anatomy of the first real eval (as built)

> **Status:** phases 0–4 are built and run on the fake tier. The shape below is the real
> `evals/10-priya/eval.yaml` (abridged). Field names were verified against Vally 0.20.0 with
> `vally lint`; see `docs/VERIFY.md` for what changed from the original sketch (no
> `tool-call-count` grader; `program` takes `program`/`args`; `completed` needs a
> `turn_end`).

```yaml
name: priya-support
type: capability

defaults:
  runs: 3
  timeout: 2m
  executor:
    name: hermes
    config: { hermes_bin: fake, profile: pd-priya, task: draft_reply }   # hermes_bin: hermes for real tier

grading_environment:            # staged only after the agent finishes; graders only
  files:
    - src: ../../hidden/priya.expected.json
      dest: .vally-grading/expected.json
    - src: ../../graders/check-draft.mjs
      dest: .vally-grading/check-draft.mjs

stimuli:
  - name: priya-002-refund
    prompt: "Draft a reply to fixture priya-002."
    tags: { fixture: priya-002 }          # the executor reads the fixture id from here
    graders:
      - type: completed
      - type: tool-calls
        config:
          required:
            - { name: "^pd_run_check$", args: { check: "^refund_eligibility$" } }
          sequence: ["^pd_read_fixture$", "^pd_run_check$", "^pd_draft_reply$"]
      - type: program
        config: { program: node, args: [.vally-grading/check-draft.mjs, .vally-grading/expected.json] }

scoring:
  weights: { completed: 0.2, tool-calls: 0.3, program: 0.5 }
  threshold: 1.0
```

The `prompt` (LLM judge) grader is added in phase 5, after static graders pass.
Line-by-line notes for learners live in `docs/EVAL_SPEC_WALKTHROUGH.md`.

Where the evidence lives: PersonaDesk's real artifact is the **stored draft** written by
`pd_draft_reply`, not the chat text. The driver writes `personadesk-out/job.json` (job
record plus stored draft) into the trial `workDir`, and `personadesk-out/draft.txt` only
when the job reached `awaiting_review`. `graders/check-draft.mjs` is a `program` grader that
compares `job.json` with the hidden answer key: status, persona ownership, cited fixture,
required and forbidden policies, recorded blocked actions, and must/must-not phrases.

---

## 5. Architecture

```mermaid
flowchart LR
  spec["eval.yaml<br/>(stimuli, graders, scoring)"] --> vally["vally eval<br/>(Node ≥ 22.14)"]
  vally -->|"--executor-plugin"| exec["vally-hermes-executor<br/>(plain JS, ESM)"]
  exec -->|"spawn per trial"| driver["run_personadesk_job.py<br/>(production run_job)"]
  driver --> hermes["hermes -p pd-* chat --oneshot<br/>--format stream-json"]
  driver -. "light tier" .-> fake["scripts/fake_hermes.py<br/>(same protocol, no model)"]
  hermes --> plugin["PersonaDesk plugin<br/>tools + pre_tool_call guard"]
  plugin --> work["per-trial workDir<br/>drafts, review records"]
  hermes -->|"JSONL events"| exec
  exec -->|"Trajectory"| graders["Vally graders<br/>static → program → LLM judge"]
  work --> graders
  hidden["grading_environment<br/>(hidden answer keys)"] --> graders
  graders --> results["results.jsonl<br/>docs/evidence/"]
```

Isolation per trial: Vally gives every trial its own `workDir`. The driver puts the trial's
PersonaDesk job store (`state.db`), stream copy and results under
`<workDir>/personadesk-out/`, so trials never share drafts. PersonaDesk's single global job
lock (`artifacts/locks/personadesk-gpu.lock`) and the `active-job.json` token binding are
per machine, so **every** Hermes-executor run, fake tier included, uses `--workers 1`. A busy
lock is reported to Vally as a retryable error.

Secrets: model keys stay in the environment of the **vally process** and Hermes's own
`.env`; eval specs reference env-var names only. Vally's provider blocks accept no literal
key field, which is the same rule this repository already follows.

---

## 6. Phases, each with a gate

| Phase | Build | Gate (must pass to continue) |
|---|---|---|
| **0. Verify** | Install Node ≥ 22.14 and `@microsoft/vally-cli` (0.20.0 at time of writing). Record versions, telemetry behaviour and the opt-out, and where results are written, in `docs/VERIFY.md`. Confirm `hermes chat --oneshot --format stream-json` on the pinned Hermes. | `docs/VERIFY.md` filled in with commands and observed output; telemetry stance documented |
| **1. First specs, no agent** | `evals/00-hello/` with the `mock` executor; run `vally lint` and `vally eval`; write `docs/EVAL_SPEC_WALKTHROUGH.md`. Deliberately break a spec (bad weights, missing grader) to see lint errors. | Lint clean; learner can explain each field; a broken spec fails for the expected reason |
| **2. Hermes executor** | `vally-hermes-executor/`: `execute()` spawns Hermes, parses JSONL, builds the trajectory, honours `timeout` and `max_agent_duration`, marks infra failures `retryable`, cleans up in `shutdown()`. Unit tests feed recorded JSONL, including malformed lines, a non-zero exit, and a timeout. | Unit tests pass; `evals/01-fake/` runs end to end against `fake_hermes.py` with no network |
| **3. PersonaDesk capability evals** | `evals/10-priya/`, `11-daniel/`, `12-noah/`: one stimulus per fixture; static graders + `graders/check-draft.mjs`; hidden answer keys under `hidden/`. | Fake tier: pass^3 = 1.0. Real tier: results recorded, failures triaged in `docs/evidence/` |
| **4. Safety gate** | `evals/20-safety/` (`type: capability`, tagged `gate: release-blocker`; Vally's `regression` type means baseline comparison): each persona's mixed-request fixture, blocked actions and cross-persona fixture reads `disallowed`, stored-draft checks. `evals/20-safety/controls/` replays a hand-written unsafe trajectory through the same graders. Prompt-injection and lock-skipping stimuli need the real tier. | Safety eval 100% on every run; the control eval **fails** for the named reasons |
| **5. Judge and compare** | Add `prompt` judges with rubrics from each `SOUL.md`; the judge model differs from the agent model. Use `vally compare` for hosted writer vs Workshop 1 local LoRA writer, and router baseline vs Workshop 3 student (advisory). | Judge agreement spot-checked by a human on ≥ 10 trials; disagreements recorded |
| **6. Multi-turn** | `supportsMultiTurn`: turn 0 runs `--oneshot`, later turns use `--resume <session_id>`. Evals for follow-up corrections ("make it shorter"). | Turn-scoped graders pass on the fake tier; real-tier evidence recorded |
| **7. Gates for other workshops** | `evals/suites/`: a `vally` suite that Workshop 5 can run before shipping a persona, and a doc showing how the Workshop 3 parity gate could be re-expressed as a Vally regression eval. | Suite runs from the repository root with one command; documented in this workshop's README |

Every phase ends with a short `docs/evidence/PHASE_<n>.md`: commands run, versions, raw
result paths, and what was learned. No numbers outside those files.

---

## 7. Hardware and cost tiers

| Tier | Agent | Judge | Needs | Purpose |
|---|---|---|---|---|
| **Light (default)** | `fake_hermes.py` | none (static graders only) | Laptop, Node, Python | Learn specs, graders, executor; zero model cost |
| **Hosted** | Real Hermes profiles on the Foundry model from Workshop 2 | A different hosted model | Workshop 2 setup and key | Real capability and safety evidence |
| **Local** | Hermes against the local writer (10 GB NVIDIA GPU or DGX Spark) | Hosted or second local model | Workshop 1/3 stack | Compare cost and quality; same evals unchanged |

Cost per eval run is roughly
`stimuli × runs × (agent tokens + judge tokens)`. Phase 3 records actual token counts
from the trajectories (`token_usage`) and from Hermes's `state.db`, and computes cost with
the Workshop 2 cost model. Keep `runs` low and judges off until static graders pass.

---

## 8. Layout (as built through phase 4)

```text
workshops/agent-evals-vally/
├── PLAN.md                         # this file
├── README.md                       # how to run each phase
├── package.json                    # pins Vally 0.20.0; links the executor as a local package
├── scripts/
│   ├── vally.mjs                   # runs the pinned CLI with telemetry off
│   ├── run_personadesk_job.py      # trial driver: production run_job, writes personadesk-out/
│   ├── tee_hermes.py               # copies the stream, enforces the time limit, kills the tree
│   └── _personadesk.py             # locates the Workshop 2 code
├── vally-hermes-executor/
│   ├── package.json                # type=module, peer dep @microsoft/vally
│   ├── src/index.js                # registerExecutors(registry)
│   ├── src/hermes-executor.js      # spawn driver, time limits, cleanup
│   ├── src/stream-to-trajectory.js # pure JSONL → trajectory mapping
│   └── tests/                      # recorded JSONL streams + unit/integration tests
├── evals/
│   ├── 00-hello/                   # mock executor, positive + negative stimulus
│   ├── 01-fake/                    # hermes executor → fake_hermes.py, two negative controls
│   ├── 10-priya/ 11-daniel/ 12-noah/
│   └── 20-safety/                  # safety gate + controls/ (must fail)
├── lessons/broken/eval.yaml        # deliberately broken spec for reading lint errors
├── graders/
│   ├── check-draft.mjs             # program grader over the stored draft
│   └── tests/
├── hidden/                         # grading_environment sources; never staged to agents
└── docs/
    ├── VERIFY.md  EVAL_SPEC_WALKTHROUGH.md  GAPS.md
    └── evidence/
```

`evals/suites/` and `.vally.yaml` arrive with phase 7.

`hidden/` sits outside every directory staged through `agent_environment`, as Vally's
guide requires, so answer keys can never be copied into the agent's workspace.

---

## 9. Tests for the harness itself

An eval harness that is wrong produces confident nonsense, so the harness gets its own tests.

- **Mapping unit tests:** each Hermes event type → expected trajectory event; malformed
  lines counted, not fatal; text deltas reproduce the final answer byte for byte.
- **Negative controls:** a fake run that calls a blocked tool must make the safety eval
  **fail**. A grader that cannot fail is not a grader. Vally's `vally oracle` negative-
  control command is evaluated in phase 4.
- **Hidden-file test:** assert no `hidden/` content appears in any agent-visible workspace
  or in the recorded diff.
- **Timeout test:** a fake run that sleeps past `max_agent_duration` returns a partial
  trajectory with `endReason: "agent_timeout"` and leaves no orphan Hermes process.
- **Secret test:** grep `results.jsonl` and logs for key patterns; must find none.

---

## 10. Risks and open questions

| Risk | Mitigation |
|---|---|
| Vally is young (0.x); fields may change | Pin the CLI version; `vally lint` in every phase; record versions in evidence |
| CLI includes telemetry exporters | Phase 0 documents what is sent and how to disable it before any real run |
| `stream-json` omits reasoning and per-turn boundaries | Grade on tool calls, results and output; log needs in `docs/GAPS.md` |
| PersonaDesk's global lock serialises trials | `--workers 1` for every Hermes-executor eval; a busy lock is a retryable error |
| LLM judge bias or drift | Static graders carry most weight; judge differs from agent; human spot checks |
| Flaky real-model runs read as regressions | Use `runs ≥ 3`, report pass@k and pass^k, never a single trial |
| Windows vs WSL differences in process control | Test kill/timeout paths on both; document in `docs/VERIFY.md` |

Settled in phases 0–2 (details in `docs/VERIFY.md`): grader option names; `program` graders
run with the trial workspace as cwd and get `EVALUATE_WORKSPACE`; `src` paths resolve
relative to the eval file; `--executor-plugin` paths resolve relative to the eval file, so
the executor is installed as a local package and selected by name; results layout. Still
open: Windows behaviour of `agent_environment.commands`; whether the hidden-file guarantee
holds for every staging path (only lint's overlap check has been observed).

---

## 11. Definition of done

- A learner can run `evals/01-fake` with no model, GPU, or key and see passing and failing
  graders they can explain.
- `vally-hermes-executor` has unit tests and handles timeouts, errors and cleanup.
- PersonaDesk capability and safety evals exist for Priya, Daniel and Noah, with recorded
  real-tier evidence and pass^k reported.
- At least one negative control proves each safety grader can fail.
- `vally compare` evidence exists for one hosted-vs-local comparison.
- No absolute paths, secrets, or real company names anywhere in the workshop.
