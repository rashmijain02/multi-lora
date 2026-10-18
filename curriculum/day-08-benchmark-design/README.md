# Day 8: Design a Reproducible Benchmark

## Outcome

Create a benchmark that can distinguish base-runtime performance, adapter overhead, cache effects, and operational behavior across candidate architectures.

## Step 1: Write the benchmark question

Use a decision-oriented question:

> Under the target prompt/output distribution and adapter popularity, which candidate meets the p95/p99 SLO at expected and peak concurrency while staying within GPU memory and cost limits?

Avoid "which engine is fastest?" because it lacks workload and decision context.

## Step 2: Freeze the controlled variables

Record:

- model and revision;
- tokenizer;
- adapter artifacts;
- adapter rank/modules;
- precision and quantization;
- GPU type/count;
- CPU/RAM/storage;
- runtime versions and container digests;
- parallelism;
- batch and scheduler controls;
- prompt/output distribution;
- request client and network location;
- warmup and measurement periods.

## Step 3: Define scenarios

At minimum:

| ID | Scenario | Purpose |
|---|---|---|
| B0 | Base model, no adapter | Runtime baseline |
| A1 | One hot adapter | Adapter kernel overhead |
| A2 | Alternating two hot adapters | Mixed-adapter batching |
| A10 | Ten adapters, uniform | Moderate diversity |
| AZ | Zipfian hot/cold population | Realistic cache behavior |
| C1 | One cold adapter | Load penalty |
| CB | Cold-adapter burst | Cache/thundering-herd behavior |
| E1 | Incompatible adapter | Error correctness |
| U1 | Adapter update/rollback | Lifecycle disruption |
| S1 | Scale-out under load | Replica readiness and consistency |

Run steady-state and burst variants at multiple concurrency levels.

## Step 4: Define metrics precisely

- **TTFT:** client send to first response token.
- **Inter-token latency:** time between streamed output tokens.
- **End-to-end latency:** client send to final token.
- **Throughput:** successful output tokens per wall-clock second.
- **Goodput:** requests meeting all SLOs per second.
- **Cold-load penalty:** cold TTFT minus matched hot TTFT.
- **Adapter-switch overhead:** matched adapted versus base latency.
- **Cache hit rate:** by storage tier, not one aggregate.
- **Error rate:** by error class.
- **GPU memory:** steady and peak.
- **Cost efficiency:** good output tokens or SLO-compliant requests per dollar.

Report p50, p95, and p99; means alone conceal tail behavior.

## Step 5: Avoid common validity errors

- Do not compare different model revisions or quantization.
- Do not let one system receive shorter outputs.
- Do not include warmup in one result and exclude it from another.
- Do not benchmark from different network locations.
- Do not infer server-side timing only from client aggregates.
- Do not use uncontrolled external APIs for microarchitectural conclusions.
- Do not claim statistical significance from one run.

## Step 6: Define execution protocol

1. Provision a fresh or documented environment.
2. Record image digests and configuration.
3. Verify correctness with deterministic prompts.
4. Warm the base model.
5. Run explicit adapter warmup where required.
6. Execute at least three independent repetitions.
7. randomize candidate order when practical;
8. collect client, server, GPU, cache, and platform metrics;
9. preserve raw results;
10. calculate confidence intervals;
11. record anomalies without deleting inconvenient runs.

## Step 7: Define pass/fail before testing

Example:

```text
p95 TTFT <= 1.5 s at expected load
p99 end-to-end <= 8 s
error rate < 0.1%
cold adapter p95 TTFT <= 5 s
no incorrect base-model fallback
GPU memory headroom >= 10%
all replicas converge to new adapter version <= 2 min
```

Replace values with Day 1 requirements.

## Deliverables

1. `benchmark-protocol.md`
2. `test-matrix.csv`
3. `environment-manifest.md`
4. `metrics-schema.json`
5. `analysis-plan.md`

## Exit check

- [ ] The benchmark answers an architecture decision.
- [ ] Workloads cover hot, cold, mixed, burst, and failure cases.
- [ ] Metrics have exact definitions and collection points.
- [ ] Pass/fail thresholds are set before results.
- [ ] Raw results and environment metadata will be retained.
- [ ] Adapter correctness is tested alongside performance.

