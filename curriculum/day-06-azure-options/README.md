# Day 6: Compare Azure Deployment Paths

## Outcome

Select the fastest viable Azure deployment path without hiding control-plane, GPU, licensing, networking, or adapter-lifecycle constraints.

## Options to compare

1. Microsoft Foundry native managed-compute adapter deployments.
2. NVIDIA NIM on Foundry/Azure ML managed online endpoints.
3. A custom vLLM, SGLang, LoRAX, or TGI container on Azure ML.
4. NVIDIA NIM on AKS.
5. An open-source serving engine on AKS.
6. A third-party managed inference endpoint only if it meets Azure boundary requirements.

## Current product-boundary facts (recheck at execution)

- Foundry native adapter deployments are a preview feature and currently use Foundry fine-tuning outputs rather than imported adapters.
- The current native multi-LoRA documentation describes multiple compatible adapters sharing one target and states a limit of eight adapter deployments per target.
- NIM on Microsoft Foundry is implemented with Azure ML managed online endpoints, which manage infrastructure and health checks but are not a serverless per-token API.
- Classic Azure ML custom-container documentation does not itself provide multi-LoRA semantics; those come from the container runtime you deploy.
- AKS provides the most control and the largest operational responsibility.

Treat these as dated inputs, not permanent platform guarantees.

## Step 1: Define the responsibility boundary

For each option identify who manages:

- GPU capacity and quota;
- VM image, driver, CUDA, and runtime;
- orchestration and replicas;
- model and adapter artifacts;
- endpoint authentication;
- TLS and network isolation;
- scaling;
- health checks;
- patching and vulnerability response;
- observability;
- NVIDIA licensing and support.

Do not label an option "fully managed" without listing the responsibilities that remain with your team.

## Step 2: Confirm regional feasibility

Record:

- required Azure region;
- supported VM SKUs;
- subscription quota and family quota;
- zone availability;
- storage locality;
- Foundry/Azure ML feature availability;
- private endpoint support;
- capacity reservation options;
- lead time for quota increases.

Treat catalog availability and deployable regional capacity as separate facts.

## Step 3: Map adapter storage

For every option evaluate:

- Foundry model registry;
- Azure ML model asset;
- Blob Storage;
- Azure Files;
- node-local NVMe;
- container image embedding;
- external model hub.

Score identity-based access, integrity verification, versioning, startup time, throughput, private networking, and rollback.

## Step 4: Compare scaling behavior

Answer:

1. What metric drives scale-out?
2. What is the cold-replica startup time?
3. How are adapters synchronized to a new replica?
4. Does scale-to-zero exist, and is it acceptable?
5. What happens to hot-adapter caches during scale-in?
6. Can each replica fit the base plus required working set?
7. Is request routing adapter-aware?

## Step 5: Compare security and governance

Check:

- Microsoft Entra ID authentication;
- managed identity for artifact access;
- private endpoint/VNet support;
- public-network disablement;
- image provenance and signing;
- artifact malware/serialization controls;
- secrets management;
- data and prompt logging;
- Azure Policy;
- audit logs;
- supported update and incident-response path.

## Step 6: Estimate cost

Include:

- GPU instance-hours and minimum replicas;
- idle capacity;
- NVIDIA AI Enterprise fees where applicable;
- storage and transactions;
- network transfer;
- logging;
- engineering and on-call effort;
- environment duplication;
- benchmark and disaster-recovery capacity.

Calculate at low, expected, and peak utilization. Avoid comparing hourly GPU cost against a serverless per-token price without a common workload.

## Step 7: Make the preliminary choice

Recommended decision form:

```text
Default path:
Why it passes the hard gates:
Primary risk:
Fallback path:
Trigger to switch:
Blocked questions:
Proof required before production:
```

## Deliverables

1. `azure-responsibility-matrix.csv`
2. `regional-capacity-check.md`
3. `azure-deployment-matrix.csv`
4. `cost-model.csv`
5. `recommended-default.md`

## Exit check

- [ ] Every path has a clear operator/vendor responsibility boundary.
- [ ] Region and GPU quota are checked, not assumed.
- [ ] Adapter storage and replica synchronization are designed.
- [ ] Security requirements are hard gates.
- [ ] Cost uses a common workload and includes idle capacity.
- [ ] A fallback path and switch trigger exist.
