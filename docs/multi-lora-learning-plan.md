# Multi-LoRA Learning Plan

> **Executable version:** The complete day-by-day curriculum, local papers, source catalog, and templates are in [`../curriculum/`](../curriculum/README.md). This document is the summary plan; each linked daily guide contains the detailed procedure, worksheets, evidence rules, deliverables, and exit checks.

## Objective
Complete a very aggressive 2-week study sprint to understand multi-LoRA serving, compare open-source and vendor implementations, verify NVIDIA NIM claims, evaluate Azure deployment options, and produce a defensible architecture recommendation.

## Primary Questions
1. What is the best serving path for multi-LoRA workloads?
2. When should LoRAX, vLLM, SGLang, or NIM be used?
3. What is actually supported in Azure and NVIDIA NIM for the target model family?
4. What architecture should be recommended for production?

## Important Verification Note
Several claims in the original summary are version-dependent or must be verified directly against vendor documentation and the specific model/runtime combination. Do not treat the following as established facts without checking current docs:
- NIM multi-LoRA support for the target model
- runtime backend details (TensorRT-LLM, vLLM-derived, or version-specific)
- cache environment variables and refresh behavior
- Nemotron-specific adapter compatibility
- exact adapter loading/caching semantics

## Timeline
- Duration: 10 working days / 2 weeks maximum
- Pace: high intensity
- Output-driven: every day ends with a concrete artifact
- Assumption: basic LoRA and LLM serving concepts are already known

## Week 1 — Ground truth and technical foundations

### Day 1 — Define the target and verify claims
[Detailed Day 1 guide](../curriculum/day-01-target-and-claims/README.md)

**Goal:** Turn the summary into a verified checklist.

**Tasks**
- List all claims in the summary.
- Mark each as confirmed by docs/papers, implementation-specific, version-dependent, or unverified.
- Identify the exact target stack:
  - model family
  - adapter count
  - expected concurrency
  - latency target
  - Azure-only or hybrid
  - whether NIM is mandatory

**Deliverables**
- Assumption register
- Decision criteria sheet

**Success criteria**
- Clear understanding of what must be verified before recommendation.

### Day 2 — LoRA and multi-LoRA fundamentals
[Detailed Day 2 guide](../curriculum/day-02-lora-foundations/README.md)

**Goal:** Understand how multi-LoRA serving works at the systems level.

**Tasks**
- Review LoRA / PEFT basics.
- Study adapter composition and memory overhead per adapter.
- Understand why batching across adapters is hard.
- Review CPU RAM and GPU VRAM cache tiers.

**Deliverables**
- System diagram of multi-LoRA serving
- Glossary of key terms

**Success criteria**
- Ability to explain why multi-LoRA is harder than normal inference.

### Day 3 — Research S-LoRA, Punica, and LoRAX
[Detailed Day 3 guide](../curriculum/day-03-serving-research/README.md)

**Goal:** Learn the core technical ideas behind modern multi-LoRA engines.

**Tasks**
- Read the main papers/docs for S-LoRA, Punica, and LoRAX.
- Extract for each:
  - adapter storage strategy
  - batching strategy
  - kernel strategy
  - memory management model
  - strengths / limitations

**Deliverables**
- Comparison table
- 1-page summary per system

**Success criteria**
- Ability to explain what each system contributes technically.

### Day 4 — Compare open-source serving engines
[Detailed Day 4 guide](../curriculum/day-04-engine-comparison/README.md)

**Goal:** Understand which engine fits which workload.

**Tasks**
- Compare LoRAX, vLLM multi-LoRA, SGLang, and TGI if relevant.
- Evaluate adapter support, throughput, latency, operational complexity, deployment maturity, and Azure friendliness.

**Deliverables**
- Decision matrix
- Ranked shortlist of top 2 choices

**Success criteria**
- Defensible rationale for engine preference.

### Day 5 — Verify NVIDIA NIM reality
[Detailed Day 5 guide](../curriculum/day-05-nim-verification/README.md)

**Goal:** Separate marketing claims from actual supported behavior.

**Tasks**
- Check whether NIM supports multi-LoRA for the target model.
- Verify supported model families.
- Verify cache behavior and config knobs.
- Verify hot swapping, adapter refresh, and external storage behavior.

**Deliverables**
- NIM verification memo
- Confirmed vs unconfirmed claims list

**Success criteria**
- Exact understanding of NIM support for the target use case.

## Week 2 — Azure deployment and recommendation

### Day 6 — Azure deployment options
[Detailed Day 6 guide](../curriculum/day-06-azure-options/README.md)

**Goal:** Identify the fastest viable Azure path.

**Tasks**
- Compare Azure ML managed online endpoints, AKS, Hugging Face Inference Endpoints on Azure, and custom containers.
- Evaluate GPU availability, adapter storage options, autoscaling, networking/security, and operational overhead.

**Deliverables**
- Azure deployment options matrix
- Recommended default deployment path

**Success criteria**
- Best-fit Azure hosting model identified.

### Day 7 — Adapter storage and refresh design
[Detailed Day 7 guide](../curriculum/day-07-adapter-lifecycle/README.md)

**Goal:** Design how adapters will be stored, loaded, and refreshed.

**Tasks**
- Decide where adapters live.
- Define versioning and refresh/polling.
- Define cache invalidation.
- Define missing/corrupt adapter handling.
- Define lifecycle: upload, validation, indexing, warmup, eviction, rollback.

**Deliverables**
- Adapter lifecycle diagram
- Storage/cache policy

**Success criteria**
- End-to-end adapter operations are clearly described.

### Day 8 — Benchmark design
[Detailed Day 8 guide](../curriculum/day-08-benchmark-design/README.md)

**Goal:** Define the minimum benchmark needed for a real comparison.

**Tasks**
- Choose metrics: tokens/sec, time-to-first-token, p95/p99 latency, adapter switch overhead, GPU memory utilization, cold-start cost.
- Define scenarios: single adapter repeated, many adapters evenly distributed, Zipfian hot/cold mix, burst traffic.
- Define baselines: base model only, LoRAX or vLLM, NIM if supported.

**Deliverables**
- Benchmark plan
- Test matrix with workloads

**Success criteria**
- A practical proof plan exists for comparison.

### Day 9 — Synthesize findings into an architecture recommendation
[Detailed Day 9 guide](../curriculum/day-09-architecture-decision/README.md)

**Goal:** Turn research into a decision.

**Tasks**
- Score options against criteria: performance, maturity, Azure fit, NIM support, operational simplicity, cost.
- Write recommendation for primary path, fallback path, and no-go conditions.
- Include assumptions and risks.

**Deliverables**
- 2–3 page architecture recommendation
- Executive summary slide

**Success criteria**
- Defensible recommendation produced.

### Day 10 — Final review and action plan
[Detailed Day 10 guide](../curriculum/day-10-final-review/README.md)

**Goal:** Convert the study into next steps.

**Tasks**
- Review all artifacts.
- Identify remaining gaps that require lab testing.
- Decide whether to prototype, benchmark, or proceed to deployment planning.
- Create a 30-day follow-on plan.

**Deliverables**
- Final study packet
- 30-day execution roadmap

**Success criteria**
- Another person could continue from the packet without context loss.

## Daily Time Budget
- 2–3 hours reading
- 1–2 hours synthesis
- 1–2 hours validation/comparison
- 30 minutes writing deliverable

Total: 4–7 hours/day

## Must-Read References
- Curated and annotated catalog: [curriculum source catalog](../curriculum/sources/README.md)
- Downloaded open-access papers: [local paper library](../curriculum/papers/README.md)
- S-LoRA overview: https://www.lmsys.org/blog/2023-11-15-slora/
- S-LoRA paper: https://arxiv.org/abs/2311.03285
- Punica paper: https://arxiv.org/abs/2310.18547
- SGLang LoRA docs: https://docs.sglang.io/docs/advanced_features/lora
- NVIDIA multi-LoRA vLLM Triton tutorial: https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/vllm_backend/docs/llama_multi_lora_tutorial.html
- NVIDIA NIM blog: https://developer.nvidia.com/blog/seamlessly-deploying-a-swarm-of-lora-adapters-with-nvidia-nim/
- NVIDIA NIM LoRA docs: https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/finetune-lora.html
- TensorRT-LLM LoRA docs: https://nvidia.github.io/TensorRT-LLM/advanced/lora.html
- TensorRT-LLM repository: https://github.com/NVIDIA/TensorRT-LLM
- Azure ML custom container deployment: https://learn.microsoft.com/azure/machine-learning/how-to-deploy-custom-container
- NVIDIA NIM deployment on Azure: https://docs.nvidia.com/nim/large-language-models/latest/deployment/csp-deployment/azure.html

## Fast-Start Reading List
If time is limited, read these first:
1. https://www.lmsys.org/blog/2023-11-15-slora/
2. https://arxiv.org/abs/2311.03285
3. https://arxiv.org/abs/2310.18547
4. https://docs.sglang.io/docs/advanced_features/lora
5. https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/vllm_backend/docs/llama_multi_lora_tutorial.html
6. https://developer.nvidia.com/blog/seamlessly-deploying-a-swarm-of-lora-adapters-with-nvidia-nim/
7. https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/finetune-lora.html
8. https://docs.nvidia.com/nim/large-language-models/latest/deployment/csp-deployment/azure.html

## Expected Outputs by End of 2 Weeks
- Assumption register
- Architecture comparison table
- NIM fact-check memo
- Azure deployment matrix
- Benchmark plan
- Final recommendation
- Follow-on action plan
