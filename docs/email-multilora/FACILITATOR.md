# Facilitator Guide

## Before participants arrive

1. Read the [workshop README](README.md), particularly multi-label semantics and artifact boundaries.
2. Prepare the public dataset once in each participant's run root, or share a verified read-only Hugging Face cache. Do not mix split manifests.
3. Confirm the notebook kernel is the workshop environment, not CLM or a global Python.
4. Choose whether the event includes GPU training. The CPU data/router lab stands alone but must not be described as LoRA.
5. For a short event, pretrain all four full adapters on a GPU before the session. Preserve manifests, runtime versions, and hashes. Do not replace them with fake predictions.
6. Keep smoke and full runs separate. Do not commit datasets, model weights, tokens, or executed notebooks.
7. If using vLLM, test the exact release/profile beforehand and keep its environment separate from training.
8. Run the [validation commands](README.md#validation-commands).

## Opening narrative (5 minutes)

An email assistant may receive a meeting reminder, invoice, flight confirmation, or a message that combines them. One base model can retain common language knowledge while small adapters specialize decisions.

The hypothesis is not "multi-LoRA is always better." The experiment asks whether separate task behavior and fewer selected calls improve the quality/cost trade-off for this specific workload.

## Lab 1: data and routing

Ask participants:

- Why do label counts sum to more than 2,105?
- What information would be lost if we took `labels[0]`?
- Why exclude both contradictory duplicate rows instead of picking the first?
- Why is fitting TF-IDF on all emails still a form of leakage?
- What is the difference between exact-match and micro-F1?
- Why is a maximum label probability not a calibrated probability of a domain?

Expected observations:

- Labels overlap and are imbalanced.
- The pinned source has one conflicting exact-text duplicate.
- Operations, finance, and travel do not form mutually exclusive classes.
- Lower routing thresholds usually increase recall and model calls.
- The fallback always selects at least one domain, but that can still be the wrong domain.

Exercise: compare validation routing targets 0.90, 0.95, and 0.99 in separate configurations. Choose a target before the final test, then freeze it. Do not report the best result selected after examining test outcomes.

## Lab 2: training

Before enabling `RUN_TRAINING`, have participants show:

- base model and revision;
- run root;
- train/validation/test sizes;
- smoke/full setting;
- target modules and rank;
- effective batch size;
- completion-only masks.

Ask:

- Why do finance and travel need `[]` examples?
- Can a small validation loss be achieved by always predicting `[]`?
- What would go wrong if adapter B started from adapter A's trained weights?
- Why reserve output tokens rather than right-truncate the full training sequence?
- How many base-model copies are used during independent training versus serving?

Expected answer: training creates a fresh base instance for each adapter sequentially; serving loads one base and several named adapters. These are different resource patterns.

Do not promise a training duration. Time the first adapter, record the environment, and budget the rest. If interrupted, completed adapter folders remain usable; an incomplete folder has no complete manifest and must be moved aside before retrying that adapter in the same run.

## Lab 3: evaluation

Explain the paired comparisons:

1. TF-IDF versus base: does the task even need an LLM?
2. Base versus generalist: what did tuning add?
3. Generalist versus all-specialists: what did specialization add?
4. All-specialists versus routed: what did routing remove?

Ask participants to identify:

- a finance false negative;
- a travel false positive;
- an invalid JSON response;
- a route that skipped a needed specialist;
- an exact match on all labels;
- the difference between routing label coverage and final recall.

Never "clean" malformed outputs by selecting a likely label. The strict parser intentionally makes format failures measurable. Raw responses are not persisted because they may repeat email text.

## Optional serving exercise

Use three hand-written synthetic emails. Send finance, travel, and operations requests concurrently to a server with static adapter registration.

Ask:

- Did three API calls actually share a GPU batch?
- Which telemetry would prove the scheduler's batching behavior?
- What happens if an adapter is missing from `/v1/models`?
- Why not expose runtime load/unload routes to participants?
- Why must we release the local notebook GPU model before starting vLLM?

State clearly: the concurrency demo checks endpoint routing. It is not a throughput benchmark or a NIM/Foundry certification.

## Troubleshooting

| Symptom | Response |
|---|---|
| Wrong environment / missing `email_workshop` | Select the workshop interpreter and run the editable install there |
| Dataset conflict warning | Expected: inspect the recorded quarantine; do not disable validation |
| Artifact fingerprint mismatch | Use the correct run/configuration or create a new output, never bypass the check |
| CUDA unavailable | Check the wheel/driver; use CPU only for small smoke validation |
| OOM | Close other owned GPU workloads, reduce batch/context in a new run; do not stop someone else's processes |
| Incomplete adapter directory | Preserve logs, move only that known directory aside, rerun with identical config |
| All `[]` predictions | Inspect positive recall, class imbalance, prompts, training loss; do not count negative accuracy as success |
| Invalid JSON | Report the failure; tune using validation only |
| vLLM missing adapter ID | Inspect static registration paths and startup logs |
| Timeout / HTTP error | Stop and diagnose; prior completed predictions remain checkpointed |
| No GPU or no time | Complete CPU lab; use genuine precomputed adapters/results only if their lineage is available |

## Final debrief

Participants should leave with:

- a pinned data manifest and no duplicate IDs across partitions;
- router thresholds selected without test labels;
- four adapter artifacts or an honest statement that training was not run;
- paired results with minority-label metrics and explicit failure counts;
- a clear distinction between sequential switching and heterogeneous serving;
- a next experiment rather than an unsupported production claim.

Connect this workshop to curriculum Days 2, 4, 7, and 8. Use Day 5 before changing the base model to Nemotron or the runtime to NIM.
