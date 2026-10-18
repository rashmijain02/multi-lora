# Day 4: Compare Open-Source Serving Engines

## Outcome

Produce a defensible shortlist among vLLM, SGLang, LoRAX, and TGI for the exact workload—not a generic popularity ranking.

## Scope

Evaluate each engine at a pinned version or commit. The feature comparison is invalid without versions because multi-LoRA support changes rapidly.

## Step 1: Build an evidence card for each engine

Record:

- repository and official documentation;
- release/commit evaluated;
- license;
- supported model architecture for the target;
- LoRA and multi-LoRA feature status;
- dynamic adapter loading API;
- maximum/rank constraints;
- quantization interactions;
- tensor/pipeline parallel compatibility;
- observability;
- container and Kubernetes deployment support;
- security warnings or limitations;
- maintenance indicators.

## Step 2: Verify API semantics

For each engine determine:

1. How is an adapter registered or discovered?
2. How does a request select an adapter?
3. Can adapters be added after server startup?
4. Is runtime loading explicitly safe for production?
5. What happens on duplicate names or incompatible adapters?
6. Is unloading supported?
7. Are adapter sources restricted or authenticated?
8. Does one endpoint expose base and adapted behavior?

Security note: dynamic loading from arbitrary paths or repositories can expand the trust boundary. Record allow-listing, integrity, and serialization risks.

## Step 3: Compare scheduler and memory behavior

Capture only documented or observed facts:

- mixed-adapter continuous batching;
- prefill and decode scheduling;
- GPU/CPU adapter cache;
- eviction policy;
- maximum resident adapters;
- rank and module restrictions;
- behavior under cache thrashing;
- base-model and KV-cache memory controls.

## Step 4: Test deployability on Azure

Score:

- official container availability;
- custom-container readiness;
- GPU and driver requirements;
- health/readiness endpoints;
- managed online endpoint compatibility;
- AKS deployment maturity;
- autoscaling signal quality;
- Blob Storage or model-registry integration;
- private networking and managed identity fit;
- upgrade and rollback complexity.

## Step 5: Apply hard gates

Suggested gates:

- supports the exact base architecture;
- accepts the actual adapter format;
- supports required tensor parallel degree;
- supports authenticated/private adapter storage;
- exposes health and metrics;
- license is acceptable;
- can meet deployment security constraints.

An engine that fails a gate is not rescued by its weighted score.

## Step 6: Rank with uncertainty

Score 1–5 for:

- compatibility;
- throughput potential;
- latency controls;
- adapter lifecycle;
- operational maturity;
- Azure fit;
- observability;
- community/vendor support.

Add:

- confidence from 1–5;
- evidence quality;
- unresolved test;
- sensitivity if the score changes by one point.

## Deliverables

1. `engine-evidence-cards.md`
2. `engine-decision-matrix.csv`
3. `azure-deployability-notes.md`
4. `shortlist.md` with first choice, second choice, and no-go conditions.

## Exit check

- [ ] Every engine is evaluated at a named version.
- [ ] Feature existence is separated from production safety.
- [ ] Dynamic loading trust boundaries are documented.
- [ ] The shortlist is based on Day 1 gates and weights.
- [ ] Unknowns become Day 8 benchmark cases.

