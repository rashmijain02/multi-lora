# Day 2: LoRA and Multi-LoRA Systems Foundations

## Outcome

Explain the memory, compute, and scheduling consequences of serving many adapters on one base model, including why naive per-adapter deployments waste capacity.

## Reading order

1. LoRA paper (local copy in `../papers/`).
2. Hugging Face PEFT LoRA conceptual guide.
3. vLLM LoRA documentation for one concrete serving API.
4. Revisit the exact target model configuration from Day 1.

## Step 1: Reconstruct LoRA mathematically

For a frozen weight matrix \(W \in R^{d_{out} \times d_{in}}\), write the adapted operation as:

\[
y = Wx + sBAx
\]

where \(A \in R^{r \times d_{in}}\), \(B \in R^{d_{out} \times r}\), and \(r\) is much smaller than the original dimensions.

Answer:

1. Which matrices remain frozen?
2. How does rank affect parameter count?
3. Where does the scaling factor enter?
4. Which transformer modules are targeted?
5. Why must adapter and base-model revisions match?
6. What changes when several adapters have different ranks or target modules?

## Step 2: Estimate adapter memory

For every target module, calculate:

```text
parameters = rank * (input_dimension + output_dimension)
bytes = parameters * bytes_per_element
```

Sum across layers and target modules. Add:

- serialization metadata;
- CPU staging copies;
- GPU-resident copies;
- allocator overhead;
- optional merged weights;
- cache index and request-routing metadata.

Produce estimates for ranks 8, 16, 32, and 64. Compare the adapter footprint with the base model's weights and KV cache.

## Step 3: Trace one request

Draw the path:

```text
request
  -> adapter identity validation
  -> base/adapter compatibility check
  -> cache lookup
  -> storage fetch on miss
  -> CPU staging
  -> GPU transfer
  -> scheduler admission
  -> mixed-adapter batch
  -> LoRA kernel
  -> token streaming
  -> metrics and cache accounting
```

Annotate each transition with likely latency, failure modes, and the component responsible.

## Step 4: Explain the batching problem

Compare:

- separate deployment per adapter;
- merged model per adapter;
- shared base with homogeneous adapter batches;
- shared base with heterogeneous multi-adapter batches.

Explain why ordinary batched matrix multiplication is insufficient when each request can select different low-rank matrices. Identify the role of grouped matrix multiplication, segmented operations, and adapter-aware scheduling.

## Step 5: Model the memory hierarchy

Create a diagram with:

1. object storage or model registry;
2. node-local disk;
3. host RAM cache;
4. GPU adapter cache;
5. base-model weights;
6. KV cache.

For each tier record capacity, bandwidth, eviction owner, persistence, expected hit ratio, and cold-load penalty.

## Step 6: Work a concrete example

Use the Day 1 target:

- estimate base weights;
- estimate one adapter and 100 adapters;
- choose a GPU memory budget;
- reserve memory for runtime and KV cache;
- calculate a plausible hot-adapter capacity;
- explain which values still need measurement.

Do not mistake theoretical tensor size for observed peak memory.

## Deliverables

1. `multi-lora-system-diagram.md` using Mermaid.
2. `memory-model.xlsx` or `memory-model.csv`.
3. `glossary.md`.
4. `request-walkthrough.md`.

## Exit check

- [ ] You can derive adapter parameter count.
- [ ] You can distinguish adapter memory from KV-cache memory.
- [ ] You can explain why mixed-adapter batching needs specialized kernels/scheduling.
- [ ] You can identify all cold-load boundaries.
- [ ] Every numeric estimate marks assumptions and units.

