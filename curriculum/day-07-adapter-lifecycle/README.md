# Day 7: Design the Adapter Lifecycle

## Outcome

Define a safe, observable lifecycle from adapter training output to production selection, refresh, eviction, rollback, and retirement.

## Step 1: Define the artifact contract

Each adapter version should have:

- immutable adapter ID and semantic display name;
- base model ID and exact revision;
- tokenizer revision;
- training framework and version;
- adapter type, rank, alpha, dtype, and target modules;
- checksums;
- file manifest and sizes;
- training/evaluation lineage;
- approval status;
- owner and creation time;
- compatibility test result;
- rollback predecessor;
- retention classification.

Reject artifacts missing base-model identity or integrity metadata.

## Step 2: Design the state machine

Use at least these states:

```text
uploaded
  -> quarantined
  -> validated
  -> registered
  -> staged
  -> warmed
  -> active
  -> deprecated
  -> retired
  -> deleted
```

Add failure transitions for corrupt, incompatible, revoked, and rollback-pending artifacts. Define who or what may cause each transition.

## Step 3: Define validation

Validation should include:

- manifest and checksum;
- safe serialization format;
- required files;
- base revision match;
- tensor names and target modules;
- rank/dtype limits;
- tokenizer compatibility;
- test load;
- deterministic smoke prompts;
- quality threshold;
- security and approval policy.

Never let the first production request perform the only validation.

## Step 4: Design cache tiers

For object storage, node disk, host RAM, and GPU memory specify:

- capacity;
- admission;
- eviction;
- TTL;
- prefetch trigger;
- integrity check;
- refresh mechanism;
- metrics;
- behavior during pressure;
- behavior across replicas.

Model at least:

1. a single dominant adapter;
2. uniform traffic across many adapters;
3. a Zipfian hot/cold distribution;
4. a burst of previously cold adapters.

## Step 5: Define consistency and refresh

Choose and document:

- immutable versioned paths;
- alias-to-version mapping;
- polling, events, or explicit control API;
- atomic activation;
- generation/version token in requests;
- replica convergence deadline;
- behavior for in-flight requests;
- cache invalidation;
- rollback propagation.

Prefer publishing a new immutable version and atomically moving an alias over overwriting files in place.

## Step 6: Define failures

For each condition specify status code, retryability, alert, and fallback:

- adapter not found;
- unauthorized adapter;
- checksum failure;
- base mismatch;
- unsupported rank/module;
- storage timeout;
- host-memory pressure;
- GPU-cache pressure;
- load timeout;
- partial replica rollout;
- revoked adapter;
- stale alias;
- runtime crash during load.

Do not silently fall back to the base model; that produces valid-looking but semantically incorrect responses.

## Step 7: Add observability

Minimum signals:

- requests by adapter/version;
- adapter lookup failures;
- cache hit rate by tier;
- load latency by tier;
- adapter switch/cold-load TTFT;
- eviction count and reason;
- active/resident adapter count;
- memory by base, KV cache, and adapters;
- compatibility rejection count;
- version skew across replicas;
- rollback events.

## Deliverables

1. `adapter-manifest-schema.json`
2. `adapter-state-machine.md`
3. `cache-policy.md`
4. `failure-policy.md`
5. `operational-runbook.md`

## Exit check

- [ ] Artifacts are immutable and integrity-checked.
- [ ] Compatibility is verified before activation.
- [ ] Refresh is atomic and replica convergence is measurable.
- [ ] Failure never silently selects the wrong behavior.
- [ ] Cache policy covers hot, cold, and burst traffic.
- [ ] Rollback is a tested state transition.

