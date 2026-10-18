# Day 9: Produce the Architecture Recommendation

## Outcome

Turn the evidence into a reviewable architecture decision with a primary path, fallback, risks, and proof gates.

## Step 1: Reconcile the evidence

Collect:

- Day 1 hard gates and weighted criteria;
- Day 3 technical findings;
- Day 4 engine shortlist;
- Day 5 NIM/Nemotron verdict;
- Day 6 Azure matrix and cost model;
- Day 7 lifecycle requirements;
- Day 8 benchmark thresholds.

Resolve conflicts by preferring observed results and versioned primary documentation. Keep disagreement visible if it cannot be resolved.

## Step 2: Apply gates before scores

Remove or conditionally retain any option that fails:

- exact model/adapter compatibility;
- security boundary;
- regional deployability;
- required SLO;
- artifact integrity;
- support/licensing;
- rollback requirement.

Record rejected options and reasons. This prevents later teams from repeating the same investigation.

## Step 3: Score viable options

For each score include:

- value from 1–5;
- weight;
- confidence from 1–5;
- evidence reference;
- sensitivity;
- unresolved proof.

Calculate both ordinary weighted score and confidence-adjusted score. Do not hide a low-confidence lead.

## Step 4: Draw the proposed architecture

Include:

- client and gateway;
- authentication and authorization;
- adapter routing;
- serving endpoint and replicas;
- base model source;
- adapter registry/storage;
- validation pipeline;
- cache tiers;
- telemetry;
- deployment pipeline;
- update/rollback control;
- private networking;
- failure boundaries.

Annotate data plane versus control plane and vendor-managed versus team-managed components.

## Step 5: Write the ADR

Use:

```text
Title
Status
Date
Decision owners
Context
Decision drivers
Hard constraints
Options considered
Decision
Architecture
Consequences
Risks and mitigations
Validation evidence
Conditions that invalidate this decision
Fallback
Open questions
Review date
```

## Step 6: Define no-go and switch conditions

Examples:

- exact Nemotron profile lacks adapter support;
- external adapters cannot enter the managed path;
- p95 cold-load latency exceeds the SLO;
- cache thrash makes expected workload uneconomical;
- required GPU SKU lacks regional capacity;
- managed path cannot meet private networking requirements;
- NIM licensing changes total cost beyond the threshold.

Tie every condition to an owner and action.

## Step 7: Create an executive summary

In one page:

1. decision;
2. why now;
3. evidence;
4. cost/risk;
5. next proof;
6. fallback.

Avoid unqualified phrases such as "fully supported," "infinitely scalable," or "zero operations."

## Deliverables

1. `architecture-decision.md`
2. `architecture-diagram.md`
3. `scored-options.csv`
4. `risk-register.csv`
5. `executive-summary.md`

## Exit check

- [ ] Failed options and reasons remain documented.
- [ ] Scores link to evidence and confidence.
- [ ] The diagram identifies control/data and responsibility boundaries.
- [ ] The primary path has a fallback and switch trigger.
- [ ] Risks have owners and mitigations.
- [ ] The conclusion is no broader than the verified configuration.

