# Day 1: Define the Target and Build the Claim Register

## Outcome

Turn a broad interest in "fully managed Nemotron multi-LoRA" into a testable target. By the end of today, every important statement must have a status, scope, and required evidence.

## Time box

| Phase | Time |
|---|---:|
| Inventory and terminology | 45 min |
| Target workload definition | 60 min |
| Claim decomposition | 90 min |
| Decision criteria and weights | 60 min |
| Review and write-up | 45 min |

## Step 1: Freeze the vocabulary

Write one-sentence definitions for:

- base model and exact revision;
- LoRA adapter and adapter format;
- multi-LoRA serving;
- dynamic loading, hot loading, and hot swapping;
- adapter cache and eviction;
- managed compute, managed online endpoint, and serverless API;
- NIM model profile;
- Microsoft Foundry native adapter deployment;
- bring-your-own adapter.

If two sources use a term differently, record both meanings instead of silently choosing one.

## Step 2: Define the workload envelope

Complete the workload profile below. Use ranges where values are not known.

| Field | Required detail |
|---|---|
| Base model | Publisher, model, parameter count, exact revision |
| Adapter provenance | Foundry fine-tuning, NeMo, PEFT, or other |
| Adapter structure | Rank, target modules, dtype, base revision |
| Adapter population | Initial, expected in 90 days, maximum |
| Active working set | Concurrent hot adapters and request distribution |
| Traffic | Requests/sec, concurrent requests, prompt/output lengths |
| SLO | TTFT, inter-token latency, p95/p99 end-to-end latency |
| Availability | Target uptime and recovery objectives |
| Deployment boundary | Azure-only, hybrid, or portable |
| Operations | Team size, Kubernetes expertise, on-call constraints |
| Security | Private networking, identity, encryption, data residency |
| Economics | Budget, utilization pattern, licensing constraints |

Do not continue with an unspecified "Nemotron." Record the exact model card and revision under evaluation.

## Step 3: Atomize the claims

Break compound claims into independently verifiable statements. For example:

> "Foundry fully manages Nemotron multi-LoRA."

becomes:

1. The exact Nemotron model appears in the current Foundry catalog.
2. Its deployment type is managed compute or serverless.
3. The selected model profile supports LoRA.
4. It supports more than one adapter on a shared base deployment.
5. Externally trained PEFT adapters can be registered.
6. Adapters can be added without rebuilding or restarting the target.
7. The runtime can batch requests targeting different adapters.
8. Cache limits and eviction behavior are documented.
9. Microsoft or NVIDIA supports the resulting configuration.

For each claim, record:

- smallest precise statement;
- model and runtime scope;
- evidence needed;
- current status;
- source URL and access date;
- owner and due day;
- consequence if false.

## Step 4: Define decision criteria

Score criteria from 1 (weak) to 5 (strong) and assign weights totaling 100%.

Suggested starting weights:

| Criterion | Weight |
|---|---:|
| Verified model/adapter compatibility | 20% |
| p95 latency and throughput | 15% |
| Operational burden | 15% |
| Adapter lifecycle maturity | 12% |
| Azure security/network fit | 10% |
| Cost at expected utilization | 10% |
| Reliability and support | 8% |
| Portability/lock-in | 5% |
| Observability | 5% |

Add hard gates separately. A weighted score must never compensate for a failed hard requirement.

## Step 5: Create explicit hypotheses

Write falsifiable hypotheses such as:

- H1: One base deployment can serve at least 100 compatible adapters without one GPU-resident model copy per adapter.
- H2: A cold adapter reaches the target TTFT within the SLO.
- H3: The managed option accepts an externally trained adapter for the exact Nemotron revision.
- H4: Requests for different adapters can share a continuous batch.
- H5: Adapter rollback does not require replacing the base deployment.

## Deliverables

Create:

1. `assumption-register.md`
2. `decision-criteria.md`
3. `target-workload.md`
4. `claim-register.csv`

Recommended claim register columns:

```csv
id,claim,scope,status,evidence_type,source,accessed,owner,due_day,impact_if_false,notes
```

## Exit check

- [ ] The exact model and revision are named.
- [ ] "Managed" and "serverless" are not used interchangeably.
- [ ] Every architecture-changing claim has a required evidence type.
- [ ] Hard gates are separate from weighted preferences.
- [ ] Unknowns have owners and deadlines.
- [ ] No vendor blog is treated as proof of a version-specific runtime behavior.

