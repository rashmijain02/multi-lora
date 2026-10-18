# Day 3: S-LoRA, Punica, and LoRAX

## Outcome

Understand the ideas that made high-density multi-LoRA serving practical and separate research contributions from production implementation characteristics.

## Reading order

1. S-LoRA paper and project overview.
2. Punica paper and repository.
3. LoRAX documentation and repository architecture.
4. Relevant release notes/issues for current maintenance status.

Read papers in three passes:

- Pass 1: abstract, problem, figures, conclusion.
- Pass 2: architecture, algorithms, evaluation setup.
- Pass 3: limitations, assumptions, and details relevant to the target workload.

## Step 1: Extract each problem statement

For each system answer:

- What bottleneck is being removed?
- What baseline is considered inadequate?
- What scale is claimed?
- Which model families, GPUs, adapter ranks, and request distributions were tested?
- Is the contribution a kernel, scheduler, cache, memory manager, server, or combination?

## Step 2: Study Punica

Focus on:

- how requests for different adapters are grouped;
- the segmented-gather matrix-vector multiplication approach;
- prefill versus decode behavior;
- supported ranks and shapes in the evaluated system;
- how reported throughput depends on experimental conditions.

Record what is a paper contribution versus what current downstream runtimes actually adopted.

## Step 3: Study S-LoRA

Focus on:

- unified paging of adapter weights;
- GPU and CPU adapter memory;
- tensor parallelism;
- heterogeneous adapter ranks;
- scheduler interaction;
- claims about adapter scale;
- comparison methodology and hardware.

Do not translate "can store/serve thousands" into "thousands are simultaneously GPU-resident."

## Step 4: Study LoRAX

Focus on:

- adapter source and loading interface;
- dynamic loading behavior;
- batching and routing;
- cache configuration;
- supported base architectures;
- production API surface;
- repository activity and release maturity.

Distinguish documented behavior from behavior inferred from source or issues.

## Step 5: Build the comparison

Use this schema:

| Dimension | S-LoRA | Punica | LoRAX |
|---|---|---|---|
| Primary contribution | | | |
| Artifact type | | | |
| Base model loading | | | |
| Adapter storage tiers | | | |
| Adapter routing | | | |
| Mixed-adapter batching | | | |
| Kernel approach | | | |
| Rank constraints | | | |
| Tensor parallelism | | | |
| Cache/eviction | | | |
| Evaluated hardware | | | |
| Workload assumptions | | | |
| Production maturity | | | |
| Target-model evidence | | | |

Every cell must contain either a citation, `not documented`, or `not applicable`.

## Step 6: Reconcile claims

Select five headline performance or scale claims. For each:

1. quote or paraphrase precisely;
2. capture the test setup;
3. identify the baseline;
4. identify what was held constant;
5. list reasons the result might not transfer to Nemotron on Azure;
6. define a reproduction test.

## Deliverables

1. `slora-notes.md`
2. `punica-notes.md`
3. `lorax-notes.md`
4. `research-comparison.csv`
5. `claim-transferability.md`

## Exit check

- [ ] Research prototypes and deployable servers are not scored as equivalent artifacts.
- [ ] Performance claims include hardware and workload context.
- [ ] Adapter capacity is distinguished from active GPU residency.
- [ ] Current project maintenance is checked separately from the paper date.
- [ ] At least three ideas are translated into benchmark hypotheses.

