# Change Assurance Lab

## Hermes-driven, goal-oriented quality engineering with LLMs and small models

**Status:** research-backed workshop proposal; not implemented or benchmarked.
**Research snapshot:** 2026-11-09.
**Intended use:** personal, noncommercial learning, with public GitHub code and learning
materials under an intended MIT or equivalent permissive license for original contributions.
Third-party assets retain their own terms; follow the shared
[publication policy](../../README.md#personal-learning-publication-policy).
**Audience:** software engineers, quality engineers, ML engineers, and CI/platform teams.
**Format:** eight three-hour labs after facilitator preparation, followed by an optional
six-week shadow-mode SDLC pilot.
**Primary implementation scope:** Python libraries, pytest, deterministic unit/component
tests, local inference, and disposable Linux execution environments.
**Orchestration decision:** Hermes is the agent harness; a separate deterministic QE
controller owns execution, scoring, budgets, and release decisions.
**Automation contract:** after one-time scope and resource approval, eligible PR jobs and
bounded improvement campaigns run without per-step human prompting. Ambiguous contracts
and unauthorized actions terminate or escalate; automation does not authorize deployment.

## 1. Recommendation: build a change challenger, not another coding chatbot

Build a system that receives a bug report or pull request and asks:

> What is the cheapest executable counterexample that would expose a wrong or incomplete
> change, and can a small local model find it without losing the defect-detection power
> of a more expensive LLM-driven workflow?

The deliverable is a **Hermes-operated quality-engineering sidecar for CI**, read-only
toward the source repository and write-capable only in its isolated experiment/artifact
store. It proposes tests, executes them against controlled code versions, and produces an
evidence bundle. A scheduled Hermes goal then improves the challenger itself through
bounded, independently scored hill climbing.
It never merges code, deploys changes, modifies protected tests, or declares correctness
because a model says "looks good."

The central innovation hypothesis is **execution-grounded test selection**:

1. A fixed generator proposes candidate tests and plausible fault hypotheses.
2. A local 4B model ranks what to run next using the change, contract, test metadata,
   remaining budget, and execution evidence observed so far.
3. A deterministic controller enforces scope, budgets, and allowed actions.
4. An isolated harness checks behavior, failure causes, and repeatability.
5. Insufficient evidence produces an explicit unresolved result, not a green assurance.

The research question is not whether AI can write pytest. It is whether a small,
execution-trained policy can improve **real defect detection per CI minute and per model
token**, without silently missing defects or inheriting a coding agent's assumptions.

There are two loops: the **inner PR loop** selects and runs counterexamples for one
immutable change; the **outer research loop** changes one challenger component, measures
it on development cases, and keeps or discards the experiment. Neither loop can rewrite
its own success criteria. A complete fictional release scenario is in section 8.

### Concrete workshop demonstration

Use an explicitly constructed cache example before moving to real repositories:

- Contract: entries expire at the documented boundary; non-expired entries remain
  cache hits; zero and absent TTL have separately specified meanings.
- A proposed repair fixes an expiry boundary but accidentally disables normal caching.
- Existing tests and a newly generated boundary test pass.
- The challenger selects a contract-grounded cache-hit preservation test using a fake
  clock and an observable loader-call count.
- That test passes on an independently reviewed correct implementation and fails on
  the incomplete repair for the expected reason.
- The report identifies the counterexample, exact revision, test, and contract reference.

This is a teaching fixture, not a claimed discovery. No sleeps, production traffic, or
external services are needed. Real-case labs then use historical issues and patches.

## 2. Research landscape: what already exists and what remains open

The table distinguishes a research direction, its evidence, and the proposed extension.
It is a targeted review, not a claim of exhaustive coverage or universal SOTA.

| Direction | Representative work and verified evidence | What it does not establish | Workshop decision |
|---|---|---|---|
| Coverage-guided test improvement | TestGen-LLM at Meta [S1]; CoverUp, FSE 2025 [S2]. Both use execution feedback to filter or improve generated tests | More executed lines do not establish correct assertions or actual fault detection | Mandatory baseline, not the innovation |
| Concern/mutation-guided hardening | Meta ACH [S3] generates concern-specific mutants and tests that kill them; deployed industrially | Killing generated faults is not proof of catching independently occurring faults; equivalent and unrealistic mutants remain problems | Reproduce the mechanism on a small scope; hold out fault families |
| Just-in-time catching tests | FSE 2025 keynote paper explicitly distinguishes hardening from catching regressions before production [S4] | Generating useful tests fast enough for a live change remains different from offline coverage improvement | Primary research area |
| Issue-to-reproduction tests | SWT-Bench [S5], AssertFlip [S7], and recent specialist agents evaluate tests that fail before a repair and pass after it | A test can reproduce one symptom without rejecting an incomplete repair or detecting a new regression | Use as an external benchmark, then add patch-discrimination evaluation |
| Joint repair and testing | PatchTwin / PatchTwin+Guard [S8] generate code and reproduction tests and inspect disagreement | Joint generation and a guard are already prior art; model agreement is not an independent oracle | Explicit related-work comparator; do not claim this idea as new |
| Executable synthetic training | SWE-smith [S9] generates repository tasks and execution-grounded training data | Synthetic success does not establish unseen-repository or real-PR generalization; its reported 32B agent is not a 4B result | Use a restricted training pool, not the final test set |
| Long-horizon repository engineering | SWE-Bench Pro [S10] covers more complex, multi-file tasks with public and nonpublic partitions | A Python unit-test MVP cannot claim enterprise-SDLC coverage or compare against inaccessible private tasks | Later extension, not the initial success criterion |

### Evidence worth taking seriously

- **TestGen-LLM:** its paper reports 75% of generated test cases built, 57% passed reliably,
  and 25% increased coverage in its stated evaluation. Engineer acceptance was 73% in
  the reported test-a-thons [S1]. These are different denominators and outcomes, not a
  single "73% testing accuracy" claim.
- **CoverUp:** its paper reports median per-module line-plus-branch coverage of 80% versus
  CodaMosa's 47%, and a separate comparison of 89% versus MuTAP's 77% [S2]. These numbers
  support coverage-guided generation, not a defect-detection guarantee.
- **ACH:** its paper describes application to 10,795 Kotlin classes, producing 9,095
  mutants and 571 privacy-hardening tests [S3]. This is evidence that the workflow can
  operate in industry; reproducing that scale is outside this workshop.
- **Current SWT-Bench activity:** the official site's 2026-11-02 update reports Bugstack
  at 91.5% success on Verified in unit-test mode; its 2026-11-03 update reports Claude
  Code with Opus 5.5 at 87.8% in that mode [S6]. These are source-reported leaderboard
  observations, not results reproduced here or universal SOTA across settings.
- **Recent synthesis:** a September 2026 revision of a systematic review covers 178
  publications available through July 2026 and still identifies oracle correctness,
  fault detection, maintainability, and industrial reliability as open concerns [S11].

Leaderboards must be read with their mode, harness revision, candidate budget, model,
selection procedure, and eligible instance count. SWT-Bench's current repository lists
276 Lite and 433 Verified instances in its gold-validation table [S5]; do not silently
substitute the 300-task SWE-bench Lite denominator. Unit tests and standalone reproduction
scripts are also different settings. We will not compare a handpicked workshop subset
with a full leaderboard result.

## 3. Specific research contribution and falsifiable hypotheses

**Proposed contribution:** a budgeted SLM policy for selecting executable counterexamples
and escalating uncertainty, evaluated against real defects and plausible incomplete
patches under independent, contract-grounded grading.

This combines known techniques. It is an **innovation hypothesis**, not a verified
first-of-its-kind claim. A publication requires a deeper related-work review, fair
reproduction, and positive or informative negative results.

| Hypothesis | Experiment | Result that would reject the claim |
|---|---|---|
| H1: selection matters more than simply generating more tests | Give random, diff/coverage heuristic, LLM, and SLM selectors the same candidate pool and execution budget | SLM does not improve the number of independently confirmed defects detected |
| H2: execution-grounded training is better than imitating LLM verdicts | Compare instruction-only, teacher-choice distillation, and outcome-labeled training | Execution labels provide no improvement on held-out repositories |
| H3: a small model can replace one expensive role | Compare local 4B selection with an approved larger-model selector at matched detection targets | Detection loss exceeds a preregistered noninferiority margin or savings vanish after total cost accounting |
| H4: targeted mutation improves real-patch discrimination | Compare coverage-only tests, random-mutation tests, and concern-guided tests on independently labeled historical patches | Only generated-mutant scores improve; real-defect detection does not |
| H5: explicit escalation is useful | Compare risk/coverage and operator burden with and without abstention | Safety improvement is achieved only by refusing almost everything |
| H6: bounded goal-oriented improvement beats a fixed challenger | Compare a frozen Hermes policy with a hill-climbed challenger and equal-budget random/configuration search on fresh evaluation cases | Gains disappear outside the development set, or improvement costs exceed the operational savings |

Do not start with reinforcement learning or a multi-agent swarm. Start with fixed
candidate pools and supervised ranking inside a bounded Hermes workflow. Hill climbing
here means one controlled challenger change per experiment, not unconstrained online RL.
Contextual-bandit or RL policies are stretch work only after a stable benchmark exists.

### What the small model actually learns

At each step the input contains:

- contract/issue text available at that point in the SDLC;
- bounded diff and relevant source/test context;
- candidate test ID, description, static features, and estimated execution cost;
- previous allowed test outcomes and remaining time/token budget.

The output is a constrained choice: `RUN(candidate_id)`, `REQUEST_CONTEXT(scope)`,
`ESCALATE(reason)`, or `STOP_NO_COUNTEREXAMPLE`.

The model does not manufacture an authoritative `SAFE_TO_MERGE` verdict. Invalid choices,
out-of-scope requests, or malformed outputs cause a logged abstention, not silent defaults.

For training, execute candidate pools on training-only defects and reviewed controls.
Label actions using **verified marginal detection gain**, duplicate-test penalties, and
measured cost. This is not a license to reward any nonzero test exit code.

Train a pairwise ranker or a constrained action-generation LoRA first. Compare against
a much smaller linear/boosted ranking baseline; if that baseline wins, use it and report
the negative SLM result honestly.

## 4. The oracle problem: tests can agree with the wrong patch

Use explicit code versions:

- `B`: pre-change/base revision.
- `C`: candidate change under review.
- `R`: independently reviewed correct reference, available only to offline evaluation.
- `M`: controlled faulty variants in a disposable evaluation environment.
- `T`: a generated test with a traceable expected-behavior justification.

### Distinguish the three testing jobs

| Job | Required observation | Important limit |
|---|---|---|
| Reproduce an existing bug | `T(B)` fails for the intended behavioral reason and `T(R)` passes | The official reference and hidden tests must not be visible to the generator in a no-oracle-feedback benchmark |
| Catch a regression introduced by a change | `T(B)` passes and `T(C)` fails under an unchanged, independently justified contract | A deliberately changed requirement may make this an intended difference; contract review is necessary |
| Challenge an incomplete repair | `T(R)` passes and `T(C)` fails; determine whether `T(B)` also fails based on the issue | Passing on `R` is supporting evidence, not proof that the reference implementation is universally correct |

For live PRs there is usually no `R`. The system therefore uses:

1. Approved requirements, public API contracts, and existing independently reviewed tests.
2. Property-based tests and metamorphic relations whose preconditions are explicitly
   justified, such as a documented round-trip or order-invariance property.
3. Base-versus-candidate comparisons where behavior is meant to remain unchanged.
4. Human review when the contract is ambiguous or a new feature changes semantics.

Do not infer the expected answer solely by executing `C` and then assert that answer.
That is useful characterization in some contexts, but it does not independently validate
the change. An LLM's explanation or a second agent's agreement is not an oracle.

### Independent evaluation boundaries

- In benchmark reproduction mode the generator sees the issue, allowed base source, and
  permitted base execution feedback. It does not see gold fixes, hidden tests, future
  commits, or reference-run feedback before submitting its final test.
- In PR mode the generator may see `B` and `C`; this is a different task and must be
  reported separately from issue-only SWT-Bench results.
- Independent evaluators can use `R` and sealed tests after generation is frozen.
- Train-time feedback is allowed only on training tasks. Held-out labels cannot enter
  retrieval indexes, prompts, fine-tuning, or repeated tuning cycles.
- Production-code and evaluator files are read-only to the test generator. A test patch
  cannot weaken existing assertions, skip tests, change dependencies, or patch the runner.
- Separate containers/processes enforce these boundaries; separate chat roles alone do not.

## 5. Data and benchmark plan

No datasets, model weights, repositories, containers, or dependencies are installed by
this proposal. Review licenses and executable content before any preparation run.
Prioritize MIT, BSD, Apache-2.0, and public-domain assets for the core learning track.
The real-SDLC scenarios may be replayed locally on public repositories; company access
or a commercial deployment is not required.

| Resource | Role | Admission and evaluation constraints |
|---|---|---|
| [SWT-Bench harness](https://github.com/logic-star-ai/swt-bench) and its linked [Verified HF snapshot](https://huggingface.co/datasets/nmuendler/SWT-Bench_Verified_bm25_27k_zsb) [S5] | External bug-reproduction evaluation | Resolve a pinned harness/data revision and eligible instance IDs; review underlying repository licenses. Generator-visible contexts must exclude evaluator secrets |
| [SWE-smith Python on HF](https://huggingface.co/datasets/SWE-bench/SWE-smith-py) [S9] | Training and development candidates with executable environments | Card declares MIT and 50,908 instances from 131 repos. Review underlying source/image rights too. Exclude evaluation repositories and derived near-duplicates before sampling |
| Independently reviewed incomplete repairs and historical regressions | Offline patch-discrimination evaluation | Prefer permissively licensed source repositories; retain upstream terms on copied/derived patches and tests. Human adjudication plus independent behavioral checks; distinguish real faults from constructed mutants |
| A local, approved Python repository's later PRs | Prospective shadow-mode pilot | Opt-in repository approval, no private-code egress, no automatic PR edits or publication; temporal cutoff fixed before testing |
| [SWE-Bench Pro](https://arxiv.org/abs/2509.16941) [S10] | Later multi-file/generalization study | Public partition only if admitted; inaccessible held-out/commercial data are not an assumed workshop dependency |

The older monolithic SWE-smith card says it is no longer actively updated and recommends
language-specific datasets. Use the Python collection above rather than assuming old
counts, revisions, or task formats remain current.

### Personal-learning default and public release boundary

Use the MIT-declared SWE-smith Python collection, an admitted permissively licensed
repository subset, original synthetic fault fixtures, and the Apache-2.0 model candidate
as the starting pool. A dataset card's MIT declaration does not override the licenses of
embedded repository code, issue text, images, or dependencies. Filter at the underlying
asset level and record exclusions before constructing splits.

SWT-Bench remains an optional external comparison until its pinned harness, context
snapshot, and selected source cases pass the same review. Nonpermissive or unresolved
cases can be discussed as prior art without being bundled into the learning repository.
SWE-Bench Pro and private prospective PRs are not required for the personal-learning core.

Public artifacts should contain original workshop code/docs, source manifests, fetch
instructions, attribution records, original teaching fixtures, and reviewed aggregate
measurements. Download datasets, source snapshots, images, and model weights locally
rather than vendoring them by default. Preserve applicable upstream licenses and notices
for any redistribution that is explicitly admitted.

Generated tests, mutations, prompts, and traces can contain or reproduce upstream code.
Review them before publishing; do not stamp every generated artifact MIT automatically.
Keep raw logs, source-containing trajectories, caches, and trained adapters/checkpoints
out of public artifacts pending separate rights, provider-term, and leakage review.
Publishing training recipes is the default even when learning is entirely noncommercial.

The Hermes publication boundary is local artifact creation only. Any future publishing
tool must require explicit approval and an artifact/license manifest; a successful
hill-climbing run cannot independently authorize uploading its training data or weights.

### Dataset design and scope

- **Teaching tier:** 12 curated cases from at least three admitted Python repositories.
  Each has a reproducible environment, contract/issue, baseline outcome, and independently
  reviewed expected outcome. This is a demonstration set, not a paper-sized evaluation.
- **Training pilot:** start with up to 2,000 executable training tasks; derive candidate
  rankings from actual outcomes. Scale only after the pipeline works and budgets are known.
- **Development:** reserve distinct repositories where feasible, not random rows from the
  same original issue. Keep all patches, mutants, tests, and traces derived from an issue
  in one partition.
- **Research evaluation:** target at least 100 held-out real-defect cases plus reviewed
  correct-change controls, with repository-grouped uncertainty estimates. This is an
  initial feasibility target, not a claim of sufficient statistical power.
- **Prospective pilot:** shadow at least 30 eligible PRs over six weeks if change volume
  permits. This measures integration and reviewer burden; it cannot establish a rare
  defect-escape rate with high confidence.

Record excluded/unbuildable cases and reasons. Freeze eligibility before comparing models;
do not remove cases just because one system failed. Report both all-attempted and
environment-valid denominators. Public pretrained models may already know old fixes;
repository holdout is not proof of pretraining decontamination. Prospective post-cutoff
changes are an essential complementary evaluation.

## 6. Implementation architecture and executable scope

```text
Approved PR event or scheduled improvement campaign
    |
    v
Hermes profile + standing goal + proposed QE plugin
    | bounded tool calls; no evaluator or production credentials
    v
Deterministic controller: job identity, permissions, budgets, state
    |
    +--> Immutable PR job: collect context, generate, select, execute
    +--> Improvement campaign: one challenger change, compare, keep/discard
    |
    +--> Fixed baseline or LLM candidate-test generator
    +--> Optional training-only mutants and selector adaptation
    |
    v
Candidate pool + bounded local SLM selector
    |
    v
Isolated executor: base / candidate / evaluator-only reference variants
    |
    v
Failure classification + repeatability + contract/evidence checks
    |
    v
Machine-readable evidence bundle + human-readable CI summary
    |
    +--> COUNTEREXAMPLE_FOUND
    +--> NO_COUNTEREXAMPLE_WITHIN_BUDGET
    +--> INCONCLUSIVE / INFRA_ERROR
```

`NO_COUNTEREXAMPLE_WITHIN_BUDGET` is explicitly not "correct" or "safe." CI must not turn
it into a new merge authorization. Existing required checks remain authoritative.

### Hermes integration: reuse mechanisms, implement the QE-specific behavior

The local [AutoResearch workflow](../autoresearch-spark/PLAN.md) already documents Hermes
profiles, `/goal`, bounded turns, resume, and a keep/discard harness. Its
[harness implementation](../../workshops/autoresearch-spark/harness/autoresearch_harness.py) provides
prior art for locked evaluation inputs, run records, scope checks, and held-out evaluation.
The [PersonaDesk plugin entry point](../../workshops/personal-agent-multilora/hermes_plugin/__init__.py)
demonstrates `register_tool`, `pre_tool_call`, and operator CLI registration.

These are existing patterns, **not an existing QE integration**. The proposed
`change-assurance` plugin, durable worker, evaluator isolation, campaign scheduling,
tool schemas below, and automatic shadow-release gates all need implementation and tests.
Do not present them as built-in Hermes capabilities.

| Layer | Responsibility | Authority it must not have |
|---|---|---|
| CI/scheduler adapter | Authenticate an approved event, enqueue a bounded job, wake the Hermes worker | Change evaluation thresholds or broaden repository access |
| Hermes profile `qe-challenger` | Maintain the goal, inspect allowed evidence, choose hypotheses and next tool calls | Declare its own score, lift budgets, access sealed labels, merge code |
| QE plugin and pre-tool guard | Bind every action to job ID, revision, allowed paths, and phase | Treat a permissive prompt or tool argument as authorization |
| Deterministic controller/runner | Enforce lifecycle, scope, resource accounting, immutable grading, and keep/discard | Accept model text as an execution result |
| Independent release evaluator | Evaluate a frozen challenger and, if authorized, update a shadow-only release alias | Reveal sealed case details to the experiment agent |
| Operator | Approve initial envelope, resolve contracts, revoke access, approve adopted tests | Quietly change a sealed experiment's criteria after seeing results |

Use one Hermes coordinator initially, not a planner/coder/reviewer swarm. The local SLM
is a bounded selector invoked through the plugin, not another autonomous orchestration
framework. Training and evaluation are ordinary supervised worker jobs.

**Proposed tools, not currently callable commands:**

| Tool | Bounded operation |
|---|---|
| `qa_open_job(job_id)` | Return the authorized goal, revisions, phase, incumbent version, and remaining budget |
| `qa_read_context(job_id, scope_id)` | Read an allowlisted context slice; never arbitrary paths or reference fixes |
| `qa_submit_tests(job_id, test_bundle)` | Validate/store new test artifacts without altering source or existing tests |
| `qa_execute(job_id, candidate_ids)` | Execute in the approved environment; controller resolves revision and limits |
| `qa_propose_trial(campaign_id, parent_id, hypothesis, candidate_delta)` | Create an immutable trial with exactly one allowlisted challenger change |
| `qa_run_trial(trial_id)` | Start a bounded experiment through the independent runner; return a durable handle |
| `qa_status(handle)` | Read durable progress, permitted diagnostics, and controller-issued verdicts |
| `qa_finish(job_id)` | Request finalization; controller verifies terminal evidence and records the outcome |

`qa_execute` has no caller-supplied shell, image, mount, credential, or timeout override.
Hermes cannot invoke the release evaluator or move the incumbent/release aliases.
Tool guards are defense in depth; OS/runner isolation protects hidden state even if the
agent emits malicious code or instructions.

### Unattended operation, recovery, and goal completion

The approved envelope fixes repository IDs, available tools, editable experiment surfaces,
data/model versions, resource limits, retention, and output destinations. Keep general
approvals enabled; do not use unrestricted execution to avoid approval prompts.
Routine in-envelope actions run through the bounded plugin. An unexpected approval need
becomes `NEEDS_APPROVAL` and stops that job instead of blocking an unattended process.

Persist job state outside chat history. Key a PR job by repository, base/head SHA, contract
version, and challenger release. Deduplicate webhook retries. A controller lease prevents
two Hermes sessions from running the same job; every expensive action has an idempotency
key, a reserved budget, and a durable worker handle.

On restart, reconcile existing worker status before launching anything new. Charge failed
attempts against budgets; do not let retries become free computation. Cancel a stale-head
job and start a separately keyed job when the PR changes. A worker supervisor enforces
deadlines even if Hermes loses its session or stops responding.

Separate lifecycle (`QUEUED`, `RUNNING`, `WAITING_WORKER`, `NEEDS_APPROVAL`,
`COMPLETED`, `FAILED`, `CANCELLED`) from the scientific outcome. A completed job can be
`INCONCLUSIVE`; a timeout cannot masquerade as `NO_COUNTEREXAMPLE_WITHIN_BUDGET`.
Persist traces, candidate hashes, costs, and verdicts so another session can resume.

Hermes's goal judge can suggest that a conversational goal is done. Only the controller
can establish that required jobs and evidence are terminal. `/goal` turn limits are a
secondary stop-loss, not the source of truth for time, money, or experiment count.

**Illustrative goal text, usable only after the proposed plugin exists:**

> Complete the approved release campaign. For each eligible PR, challenge the frozen
> change within its budget and publish the local evidence bundle. Then improve the
> challenger on the authorized development cohort, one hypothesis per trial. Use only
> the QE tools. Do not edit contracts, grading, product code, or sealed cases. Stop at
> the controller's terminal status, resource limit, or required approval; summarize the
> recorded verdict, never an inferred success.

### Small, buildable components

1. **Collector:** repository allowlist, revision pinning, diff, test discovery, dependency
   environment fingerprint, bounded source retrieval, and existing test outcomes.
2. **Generator:** pluggable fixed-prompt local model producing only candidate test files
   and contract references. Reuse a reviewed generator where practical.
3. **Selector:** deterministic heuristic, learned non-LLM ranker, local 4B model, or
   larger-model comparator behind the same constrained interface.
4. **Executor:** disposable environment, immutable reference files, per-run limits,
   structured pytest results, branch coverage, and baseline-comparison results.
5. **Evidence checker:** distinguish behavioral assertion failures from import, syntax,
   install, infrastructure, timeout, and nondeterminism failures.
6. **Reporter:** exact hashes, provenance, outcomes, costs, unresolved claims, and
   reproducible commands from the correct working directory.

Implement a Python package with pytest and coverage.py first. Use Hypothesis for approved
property-based checks where useful. Admit a maintained mutation engine only after checking
its compatibility and license; do not build a general mutation platform as the first lab.
Use HF datasets/transformers/PEFT for approved local training.

**Model candidate:** [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
has a verified 4B, Apache-2.0 model card [S12]. It is a practical narrow-role candidate,
not a claim that it is the best current coding model or that it can match frontier agents.
A larger comparator must be an approved local model or an approved service on data
explicitly cleared for that service. Private repository content stays local by default.

### Resource plan

- CPU-only tier: the harness, ranking baselines, cached/public permitted candidate pools,
  statistics, and CI reports. Cached generation is labeled replay, not live inference.
- Local 4B tier: quantized inference and optional QLoRA with short, bounded contexts.
  A 10 GB GPU is an experiment target, not a guaranteed training configuration; measure
  peak memory before allocating a workshop cohort.
- Benchmark executor: the SWT-Bench repository recommends x86_64, at least 120 GB free
  storage, 16 GB RAM, and eight CPU cores for its harness [S5]. Use a verified Linux
  container host; ARM64 support is described as experimental. A DGX Spark is therefore
  not assumed to be a drop-in benchmark executor.
- Start sequentially on a few cases. Full benchmark execution is separate from the
  small teaching tier and may be dominated by environment setup rather than inference.

### Execution safety and reproducibility

Generated tests and benchmark repositories are untrusted executable code. Use an approved
disposable VM/container boundary with no host secrets, no Docker socket, no privileged
mode, no production credentials, and no broad checkout/home mounts. A container alone
is not a complete defense against hostile code; apply the organization's runner policy.

Separate a controlled dependency/image provisioning phase from offline test execution.
Pin package/model/image revisions; disable network access during execution when feasible.
Keep generated tests away from evaluator state and reference-patch locations.
Limit CPU, memory, process count, output, disk usage, and wall time. Timeouts and crashes
are not automatically successful mutant kills or real defect detections.

Treat issue text, source comments, logs, and model output as untrusted data, not commands.
The controller owns an allowlisted action schema. An improvement campaign may propose
changes to an experimental selector, but models cannot change the active job's pinned
policy, split manifests, grading rules, or safety boundaries.

## 7. Eight labs and their tangible outputs

| Lab | Work | Output / exit condition |
|---|---|---|
| 1. Reproduce the measurement problem | Replay one passing-but-wrong repair; compare coverage, reproduction, and actual fault detection | A documented counterexample and a contract-based oracle; distinguish all three testing jobs |
| 2. Build the Hermes QE harness | Register bounded plugin tools; pin revisions and images; separate base/candidate/evaluator execution; classify failures | Reproducible F/P matrix, durable job status, and a rejected import-error false catch |
| 3. Establish honest baselines | Existing tests, diff/coverage selection, fixed local generation, random candidate order | Costed baseline report with unchanged candidate pools and grouped splits |
| 4. Mutation-guided hardening | Create a few concern-specific faults, verify reachability, generate tests, audit assertions | Kill matrix plus an explicit equivalent/unknown-mutant register; no blanket semantic-equivalence claim |
| 5. Assemble executable training data | Run training-only candidate pools; derive marginal-gain/cost labels and teacher-choice baseline | Versioned dataset manifest; source-repo and issue-family leakage checks |
| 6. Run goal-oriented hill climbing | Adapt the narrow SLM role; let Hermes propose one challenger change per trial; compare with ranker and frozen-policy baselines | Keep/discard ledger, paired reruns, stop-loss evidence, and matched-budget detection/cost curves |
| 7. Test on independent changes | Sealed real defects, incomplete repairs, valid controls, and a distinct official reproduction track | Paired confidence intervals, false-alarm/abstention analysis, and failure taxonomy |
| 8. Automate the release scenario | Trigger PR jobs and a scheduled improvement goal; inject a crash, duplicate event, and new PR head; run independent release evaluation | Unattended scenario replay, safe resume/cancellation, shadow rollback, evidence artifacts, and six-week pilot plan |

Facilitator preparation is additional: review upstream tools, select reproducible cases,
prepare correct/incorrect controls, fix the evaluation protocol, and pre-provision approved
images. Participants should know Python, pytest, Git/CI, and basic model evaluation.

The workshop reuses:

- [Small task models](../slm-task-models/PLAN.md): replace one model role only after a
  sealed parity gate, not an entire engineering workflow.
- [AutoResearch](../autoresearch-spark/PLAN.md): bounded experiments and independent,
  immutable grading; no agent self-certification.
- [Agent evaluations](../agent-evals-vally/README.md): negative controls and reproducible
  executor/reporting patterns.
- [Email Multi-LoRA](../email-multilora/README.md): training/evaluation mechanics only;
  its persona datasets are unrelated to software-quality labels.

Hermes is required for the orchestration and autonomy labs; the deterministic harness
must also run without an LLM for tests and baseline replay. Vally and multi-LoRA serving
remain optional. Do not add a competing agent framework.

## 8. Real SDLC integration, not a disconnected benchmark demo

| SDLC point | Input and action | Output and boundary |
|---|---|---|
| Requirements/design | Engineer supplies changed contract, invariants, examples, compatibility expectations | Traceable test objectives; ambiguous requirements go back for clarification |
| Local development | Developer invokes the challenger on a bounded diff | Suggested counterexamples and tests; no edits to product code |
| Pull request | Approved event launches a Hermes job with exact base/head SHAs and a fixed budget | Evidence artifact tied to those SHAs; duplicate jobs deduplicated and stale results invalidated |
| CI/regression | Run selected approved tests; escalate unresolved higher-risk changes to broader existing suites | Existing required suites are never skipped solely on an SLM recommendation |
| Nightly/pre-release | Scheduled Hermes goal runs a bounded keep/discard campaign and independent release evaluation | Challenger candidate or retained incumbent; tests await adoption review, not automatic commits |
| Post-release incident | Approved, minimized reproducer and root-cause description become a new case | Human-reviewed regression test and benchmark entry; no automatic ingestion of production payloads |

Start with one Python library or service component whose unit/component tests are
deterministic. Do not promise UI automation, mobile, distributed concurrency, hardware,
performance benchmarking, and multi-language testing in the first release.

Initial PR budget: **five minutes after environment readiness** as a planning hypothesis.
Report cold setup separately and include it in total end-to-end latency. Nightly budgets
can be larger but are fixed before comparison.

Publish a report artifact before introducing bot comments, which can create review noise.
Any later write-capable integration requires explicit permission, minimal credentials,
and provenance checks. Never execute untrusted fork PR code with privileged workflow
tokens or production secrets.

### Evidence bundle

Include schema version, repository ID, base/head hashes, contract references, model and
dataset revisions, selected tests, environment digest, command/exit status, normalized
failure category, repeat outcomes, minimal counterexample, and observed scope.

Also include elapsed generation/execution/setup time, model tokens, estimated cost
method, unexecuted candidates, budget exhaustion, and unresolved claims. Full private
logs remain within the repository's approved storage boundary and retention policy.

An evidence bundle is not a formal proof. It makes the claim reproducible and limited.

### Full scenario: a release train for a B2B inventory client

**Fictional teaching scenario.** The company, component, issue identifiers, timestamps,
and trial outcomes below are illustrative. They are not measured workshop results or
claims about an existing repository.

Northstar Supply maintains a Python client used by its order service to read warehouse
availability. The client caches availability for a configured TTL to reduce upstream
load. The team releases weekly, and its QE engineer cannot manually invent edge cases
for every SDK change. Required unit and component suites already run in CI.

**Primary user story**

> As the release QE owner, I want Hermes to challenge each inventory-client change
> against our approved behavior contracts, then improve its test-selection strategy
> overnight within a fixed budget, so that tomorrow's review has better executable
> evidence without requiring me to supervise every prompt, test, or training run.

**Developer story**

> As the SDK maintainer, I want a minimal reproducible failing test tied to my exact
> commit and the relevant contract, not an unexplained AI risk score or a flood of
> speculative comments.

**Platform-owner story**

> As the CI owner, I want duplicate events, failed workers, and interrupted Hermes
> sessions to resume safely without duplicate spend, leaked credentials, or silently
> weakened release gates.

#### Before the first unattended run

The team admits one repository, pins an environment, and approves a cache contract:

- Before expiry, repeated reads of the same key use the cache and avoid another load.
- At or after expiry, the next read refreshes the entry.
- Zero TTL bypasses caching; absent TTL follows the existing documented no-expiry rule.
- Errors and unrelated cache keys retain their documented behavior.

These are scenario-specific decisions, not universal cache semantics. A fake clock and
stubbed loader keep tests deterministic. The team also approves a development corpus,
a separate release-evaluation plan, output destinations, and all budgets. Credentials
and sealed data are never placed in the Hermes profile or generated-test sandbox.

#### A day in the workflow

| Step | Event | Automatic Hermes/controller behavior | Evidence or decision |
|---|---|---|---|
| 1. Morning PR | Issue `CACHE-217`: an entry remains valid exactly at its expiry boundary. Candidate `C1` bypasses caching too broadly while fixing the reported symptom | Event adapter starts one pinned PR job; Hermes reads the contract/diff and invokes required baseline checks | Ordinary CI and the issue-specific boundary test can pass; this is not yet a correctness verdict |
| 2. Challenge the change | Hermes proposes boundary, hit-preservation, zero-TTL, and key-isolation tests | Selector spends the bounded budget on independent behaviors; executor supplies fake-clock evidence | A second read before expiry calls the loader twice on `C1`, violating the cache-hit contract; the same test passes on `B` |
| 3. Report, not merge | The failure is repeatable and behavior-aligned | Controller records `COUNTEREXAMPLE_FOUND`, saves a test patch and trace, and finishes the PR job | Developer receives an artifact tied to `C1`; no product file or PR comment is changed automatically |
| 4. Developer correction | The maintainer supplies `C2`, restricting the expiry fix rather than disabling caching | A new-head event cancels any stale `C1` work and starts a distinct job; saved test provenance is retained | Tests are rerun on `C2`; old outcomes cannot authorize the new revision |
| 5. Finish bounded QA | No validated counterexample remains within the job budget | Hermes completes the evidence bundle; controller records `NO_COUNTEREXAMPLE_WITHIN_BUDGET` and unresolved coverage | Existing required checks and human release decisions still apply; QE has not certified correctness |
| 6. Nightly improvement | Scheduler starts the preapproved development campaign | Hermes inspects permitted failure summaries and proposes one challenger change at a time; the harness keeps/discards | A durable experiment ledger explains every attempted change and its measured development effect |
| 7. Freeze and validate | Goal reaches plateau or its hard limit | Controller freezes the best challenger; independent service runs the authorized sealed evaluation once | If all gates pass, an authorized shadow-only alias advances; otherwise the incumbent remains |
| 8. Next release cycle | New PR arrives | Worker pins the approved shadow challenger; collects latency and alert telemetry without changing required CI | A deterministic health breach rolls the alias back for future jobs; active jobs retain their pinned version |

The developer correction in step 4 is **not** an unimplemented autonomous repair promise.
The QA workflow before and after that normal SDLC event is unattended. A future coding
agent could supply `C2` through the same PR event interface, but it receives no authority
to change the challenger, evaluator, or acceptance contract.

#### Example overnight hypothesis sequence

| Trial | Hermes hypothesis / single allowed change | Illustrative harness outcome |
|---|---|---|
| A | Add a contract-grounded prompt instruction to propose a preserved-behavior test alongside the reported failing behavior | `KEEP` only if paired development evaluation improves unique defect detection without violating constraints |
| B | Treat import failures as detected defects to increase the apparent catch count | `REFUSED`: evaluator semantics are locked; a forbidden-delta attempt is recorded, not trained into the model |
| C | Prefer shorter tests so more fit into the time budget | `DISCARD` if cheap tests miss previously detected behavioral defects or increase false alarms |
| D | Train one selector adapter using already admitted, execution-labeled outcomes | `KEEP` only if the independent development comparison meets the fixed rule; training cost is charged |
| E | Repeat D unchanged until a lucky score wins | `REFUSED`: duplicate candidate/seed requests cannot create unlimited retries |

Outcomes in this table describe acceptance behavior, not fabricated performance numbers.
Keep/discard applies to experimental challenger versions, never to the developer's branch.

#### Scenario acceptance tests

An implemented workshop must demonstrate all of the following with fixture/fake-model
tests first, then an approved real-model run:

1. One approved event proceeds from intake to a persisted result without per-tool prompts.
2. The incomplete cache fix is challenged by a repeatable, contract-supported test; an
   import failure is rejected as evidence.
3. A duplicate webhook produces one logical job and no duplicated expensive execution.
4. A killed Hermes worker resumes the existing trial without resetting budgets or
   overwriting the incumbent.
5. A changed PR head makes the prior report stale; no old success is reused as new evidence.
6. Better/worse challenger fixtures yield `KEEP`/`DISCARD`; a grading mutation is refused.
7. Plateau, deadline, spend cap, and infrastructure-failure limits each terminate a run.
8. A failed sealed evaluation leaves the active shadow alias unchanged; a health-triggered
   rollback affects only future jobs and records its reason.
9. No action edits the source repository, deploys code, reads sealed references from the
   agent process, or turns a budget-limited negative result into a merge approval.

## 9. Evaluation: optimize defect detection, not a flattering proxy

### Primary endpoint

**Issue-level recall of independently confirmed real defects at a fixed total online
budget.** Each issue counts once even if many tests detect it. Match budgets for context
collection, generation, selection, and execution; report setup and offline training costs
separately as well as amortized totals.

For selector-only experiments, give every selector the same frozen candidate pool and
report both selection-time savings and full-pipeline cost. Precomputing expensive LLM
candidates does not make their cost disappear.

### Secondary metrics and definitions

| Metric | Definition / interpretation |
|---|---|
| Bug-reproduction rate | Eligible issues with an issue-aligned fail-on-base/pass-on-reference test; report official benchmark semantics separately |
| Incorrect-patch detection | Independently adjudicated wrong patches with at least one valid counterexample |
| Miss rate on known-bad patches | Bad patches producing no validated counterexample, with unresolved/abstained cases separately identified; never hide abstentions from total denominators |
| False-alarm rate | Reviewed correct changes challenged by an invalid claimed defect; include human adjudication |
| Mutant kill rate | Killed mutants among the prespecified valid, reachable evaluation mutants, with equivalent/unknown cases reported separately |
| Incremental detection | Faults caught by added tests that existing required tests missed |
| Assertion quality | Human audit of contract support, overmocking, tautologies, and candidate-derived expected values |
| Repeatability | Per-test repeated outcomes under fixed and varied approved seeds/order; report number of repeats rather than calling a small sample "flake-free" |
| Budget curve | Detection versus elapsed time, execution count, token consumption, and cost |
| Operational value | Review minutes, accepted useful tests, alerts per PR, CI latency, and unresolved rate |

### Mutation safeguards

Use different fault operators/families and seeds for training and held-out evaluation.
Do not evaluate solely on mutants produced by the same generator that supplied training
labels. Include real historical bugs and reviewed incomplete repairs.

Separate syntax-invalid, unbuildable, unreachable, already-killed, timed-out, and potentially
equivalent mutants. Keep an auditable denominator. An LLM may propose that two variants
are equivalent; it cannot establish general semantic equivalence by assertion.
Use bounded differential checks and human review, and retain an `unknown` category.

### Comparison matrix

Compare:

1. Existing required tests alone.
2. Coverage-guided generated tests with deterministic selection.
3. Concern-guided generated tests with random and diff/coverage selection.
4. Same pools with a non-LLM learned ranker.
5. Same pools with the unadapted 4B selector.
6. Same pools with the execution-trained 4B selector.
7. Same pools with a larger-model selector, if permitted.

Add a teacher-choice-distilled model to isolate whether execution labels help.
Evaluate joint repair/test approaches as a separate task, not by giving them gold
information unavailable to the other systems.

Use repeated seeds and paired issue-level comparisons; cluster/bootstrap by repository
where sample size supports it. Keep all issue derivatives together. Report confidence
intervals, effect sizes, and cost distributions rather than only one winning average.

### Goal-oriented hill climbing: a precise keep/discard contract

The outer goal is **better defect detection within fixed operational constraints**, not
lower training loss, more tests, or a higher model-generated quality score.

**Search surface:** one generator prompt revision, one context-retrieval parameter set,
one selector configuration, or one adapter/training configuration per trial. Each trial
declares which surface changed. Prompt-search, selector-search, and training experiments
are separate tracks; their costs and gains cannot be mixed into one unexplained result.
Selector-only comparisons retain identical candidate pools as required above.

**Locked surface:** contracts, source changes under test, reference fixes, case identities,
split assignments, test-failure taxonomy, objective, false-alarm limits, time/token limits,
runner code, dependencies, and release criteria. An agent cannot drop hard cases, relabel
failures, change what counts as an assertion, or redefine its resource accounting.

Let `D` be independently validated unique defects detected on the fixed development panel,
`A` false alarms on fixed correct controls, `U` unresolved cases, and `C` measured online
cost at the fixed per-case budget. The proposed lexicographic development rule is:

1. Reject invalid or out-of-scope trials before scoring; all attempts consume budget.
2. Require all safety/latency gates, and no increase in `A` or `U` versus the incumbent.
3. Keep a candidate if paired reruns support an increase in `D` of at least the frozen
   `min_detection_delta`; otherwise, at equal `D`, keep only a cost reduction exceeding
   the frozen `min_cost_delta`, without losing a mandated fault-family regression.
4. Otherwise discard. Ties retain the incumbent. Development gains are tentative, not
   evidence of generalization or proof that repeated searching "never gets worse."

Freeze the deltas after measuring baseline noise, before search. For the teaching fixture,
one extra caught issue or a 10% cost reduction can illustrate the rule; research settings
need justified deltas, paired repeats, and sufficient evaluation size. Reserve the same
rerun budget for each candidate and its incumbent; never rerun only apparent winners
until they pass.

**Proposed campaign envelope:** at most 12 trials, eight hours total elapsed time, two
training trials, and three consecutive infrastructure failures, stopping at whichever
limit is reached first. Also stop after four valid non-improving trials. Every trial has
a separate bounded runtime and the approved total spend cap is enforced by the controller.
These are configurable operator-approved starting budgets, not expected throughput.
The five-minute PR budget remains distinct from overnight training/evaluation budgets.

The lifecycle is `BASELINE -> PROPOSE -> VALIDATE_SCOPE -> RUN -> GRADE -> KEEP/DISCARD`,
with explicit `CRASH` and `REFUSED` outcomes. `CRASH` does not mean low model quality and
does not erase spend; `REFUSED` does not invite the agent to bypass a guard.
Stop conditions lead to `FREEZE -> INDEPENDENT_EVALUATION -> RELEASE_OR_RETAIN`.

Use immutable trial directories/artifacts and controller-owned incumbent pointers.
Discarding a trial means retaining the old pointer, not resetting the user's checkout.
Only the controller writes score records; hash locks help detect drift but do not replace
separate access permissions and execution boundaries.

### Prevent adaptive overfitting and automatic release mistakes

Keep three boundaries:

- Training and development cases may supply permitted execution feedback to Hermes.
  Repeated search can overfit them; log every query and failed attempt.
- A campaign's frozen candidate is evaluated once by the independent release service.
  The agent receives only the release outcome, not hidden traces, case IDs, or repair hints.
- A final paper evaluation stays separate from operational release validation and is
  not used to choose the next experiment.

Even pass/fail release feedback leaks information over repeated campaigns. Allocate
disjoint sealed release batches in advance, cap release attempts, and retire each batch
after use. Do not silently reuse the same holdout for nightly model selection. Exhausting
the approved release batches pauses release evaluation until a new dataset version is
independently admitted; development experiments may continue within their own allowance.

Within the preapproved envelope, the release service may automatically advance a
**shadow-only** challenger alias after all gates pass and persist a rollback pointer.
It may not change required CI checks, install new dependencies, adopt generated tests
into the source repository, or expand permissions. No sealed-evaluation success
automatically changes those rights.

Compare hill climbing against a frozen Hermes policy and equal-budget random/configuration
search. Account for the full optimization spend, not just the next PR's cheaper inference.
Measure fresh-case performance, reviewer burden, and plateau behavior to test H6.

### Proposed promotion gates

These are starting design targets, not observed results. Finalize them before sealed
evaluation and calculate the needed evaluation size.

- Harness gates: no reference leakage, protected-file edits, or forbidden execution;
  all known invalid-failure negative controls are rejected.
- SLM replacement: target at least a 50% reduction in larger-model selector tokens,
  with total cost reported; the paired 95% confidence lower bound on
  `SLM defect recall - larger-model defect recall` must exceed `-0.05`.
  This margin is an explicit product/research choice, not a universal safety threshold.
- Usefulness: improve defect detection over the best non-LLM baseline at the matched
  budget, or demonstrate comparable detection with a meaningful cost/latency reduction.
- False alarms: planning target <= 5% on reviewed correct controls, reported with its
  confidence interval. A small pilot with zero observed alarms does not prove this bound.
- Integration: p95 added warm-path PR time <= five minutes on the admitted scope,
  with setup, timeout, and escalation rates separately disclosed.
- Human adoption: tests require reviewer approval; report maintainability and reviewer
  burden, not only acceptance count.

Failing a gate keeps the simpler baseline and advisory-only mode. There is no stage in
this proposal that authorizes autonomous merging or replaces mandatory regression suites.

## 10. Delivery, research outcomes, and boundaries

### Implementation sequence

1. **Preparation, 1-2 weeks:** source/tool/license review, Linux runner verification,
   12-case teaching set, oracle rubric, and immutable grading contract.
2. **Hermes harness and baselines, 2 weeks:** bounded plugin tools, durable jobs, scope
   guards, deterministic reproduction/reporting, and fake-model recovery tests before
   adding any trained model.
3. **Candidate generation and training data, 2 weeks:** outcome labels, split audit,
   and static/learned baseline selectors.
4. **SLM and goal-loop experiment, 1-2 weeks:** small-model adaptation, budgeted
   hill climbing, matched-budget comparisons, ablations, and independent sealed evaluation.
5. **Workshop delivery:** eight labs; longer training/evaluation jobs run outside contact
   time with preapproved resource budgets.
6. **Optional SDLC pilot, six weeks:** unattended Hermes PR jobs and scheduled bounded
   campaigns, shadow release/rollback, reviewer feedback, latency measurement, and
   independently adjudicated outcomes.

Minimum team: one QE/CI engineer, one software engineer familiar with the pilot repository,
and one ML/research lead; roles may overlap. Add an independent evaluator/reviewer so the
same person is not inventing every oracle and judging every claimed success.

The planned artifacts are a runnable local package, Hermes QE plugin/profile setup,
goal/program template, campaign envelope, durable job/trial store, environment/data
manifests, candidate/outcome schemas, evaluator and recovery tests, an adapter if useful,
replayable reports, and a read-only CI/scheduler integration. None is claimed to exist yet,
and no Hub entry is added for an unimplemented workshop.

### Candidate research paper

*Small Models, Stronger Counterexamples: Budgeted Just-in-Time Regression Detection
Across Unseen Repositories.*

The strongest contribution would be a reproducible empirical result showing when
execution-trained SLM selection preserves or improves real-fault detection at reduced
cost, plus a benchmark of difficult incorrect patches and valid-change controls.

Possible equally useful negative results:

- A simple coverage/diff heuristic matches the SLM.
- Mutation improvements do not transfer to natural bugs.
- Domain shift destroys the apparent cost-quality advantage.
- Oracle ambiguity, flaky tests, or environment setup dominate the real CI cost.

Do not claim invention of mutation-guided generation, bug reproduction, twin patch/test
agents, or execution feedback; all have direct prior art. The proposed research delta
is the **bounded small-model policy, independently graded Hermes improvement loop,
independent patch-discrimination evaluation, and measured live-SDLC tradeoff**.

## 11. Sources and verification record

Accessed 2026-11-09. Sources below were read as paper abstracts, official project/model
documentation, or primary industry reports as indicated. Results are source-reported;
no experiments were reproduced for this proposal. Pin exact versions before implementation.

| ID | Source | Verified claim / qualification |
|---|---|---|
| S1 | [Automated Unit Test Improvement using Large Language Models at Meta, 2024](https://arxiv.org/abs/2402.09171v1) | Paper abstract: TestGen-LLM filters and reported build/pass/coverage/acceptance outcomes |
| S2 | [CoverUp, 2025 revision / FSE publication](https://arxiv.org/abs/2403.16218v4) | Paper abstract: coverage-driven iterative feedback and comparative coverage results; not a real-fault recall benchmark |
| S3 | [Mutation-Guided LLM-based Test Generation at Meta, 2025](https://arxiv.org/abs/2501.12862v1); [official ACH explanation](https://engineering.fb.com/2025/02/05/security/revolutionizing-software-testing-llm-powered-bug-catchers-meta-ach/) | Paper abstract and official report: concern-guided mutants, generated killing tests, industrial deployment |
| S4 | [Harden and Catch for Just-in-Time Assured LLM-Based Software Testing, 2025](https://arxiv.org/abs/2504.16472v2) | Paper abstract: hardening/catching distinction and JiTTest research challenge |
| S5 | [SWT-Bench harness and documentation](https://github.com/logic-star-ai/swt-bench); [paper](https://arxiv.org/abs/2406.12952) | Repository read: fail/pass task, two execution modes, linked HF datasets, instance counts, and hardware guidance. Harness revision must be frozen |
| S6 | [SWT-Bench official site](https://swtbench.com/) | November 2026 dated update observations; source-reported scores, not independently reproduced here |
| S7 | [AssertFlip replication package](https://github.com/uw-swag/AssertFlip) | Repository read: passing-test inversion, localization options, regeneration/refinement, and executable evaluation artifacts |
| S8 | [PatchTwin / PatchTwin+Guard](https://github.com/lbaf23/PatchTwin) | Repository read: joint code/test patches, post-test guard, false-agreement evaluation, and controlled tooling; not a novel feature of this proposal |
| S9 | [SWE-smith project](https://swesmith.com/); [Python HF dataset card](https://huggingface.co/datasets/SWE-bench/SWE-smith-py/blob/main/README.md); [legacy card](https://huggingface.co/datasets/SWE-bench/SWE-smith/blob/main/README.md) | Official site/card read: executable training data, 32B example, Python-specific release and MIT declaration; legacy collection deprecation note |
| S10 | [SWE-Bench Pro, 2025](https://arxiv.org/abs/2509.16941v2) | Paper abstract: 1,865 problems across 41 repositories, public/held-out/commercial partitions, multi-file long-horizon tasks |
| S11 | [Large Language Models for Unit Test Generation: Achievements, Challenges, and Opportunities, September 2026 revision](https://arxiv.org/abs/2511.21382v3) | Abstract: 178-publication review through July 2026; continuing oracle, fault-detection, and reliability concerns |
| S12 | [Qwen3-4B-Instruct-2507 model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/README.md) | Official card: 4B parameters, non-thinking instruction model, Apache-2.0; no claim of validated performance on this workshop |

**Recommended next step:** approve the 12-case, public-repository harness and baseline
experiment first. Proceed to SLM training only if the task is reproducible and selection
has room to improve. Choose the real pilot repository separately before accessing its
private code, enabling CI integrations, or spending on model runs.
