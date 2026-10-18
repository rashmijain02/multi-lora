# Multi-LoRA 10-Day Study Kit

This directory turns the study outline into an executable, artifact-driven curriculum. Work through the days in order because later decisions depend on evidence produced earlier.

## How to use this kit

1. Reserve four to seven focused hours each day.
2. Start with the day's `README.md`.
3. Read local papers first, then current vendor documentation.
4. Copy each template from `templates/` into `work/` and complete it.
5. Record every material claim with a source, access date, model version, and runtime version.
6. Do not promote a claim from `unverified` to `confirmed` based only on a blog or marketing page.
7. At the end of the day, run the exit check in the guide.

Create `work/` locally for completed worksheets if you do not want to commit work-in-progress. The supplied templates are intended to be committed and shared.

## Daily map

| Day | Focus | Required output |
|---|---|---|
| [Day 1](day-01-target-and-claims/README.md) | Target definition and claim hygiene | Assumption register and decision criteria |
| [Day 2](day-02-lora-foundations/README.md) | LoRA and multi-LoRA systems fundamentals | Systems diagram and glossary |
| [Day 3](day-03-serving-research/README.md) | S-LoRA, Punica, and LoRAX | Technical comparison |
| [Day 4](day-04-engine-comparison/README.md) | vLLM, SGLang, LoRAX, and TGI | Engine decision matrix |
| [Day 5](day-05-nim-verification/README.md) | NVIDIA NIM and Nemotron verification | Evidence-backed NIM memo |
| [Day 6](day-06-azure-options/README.md) | Microsoft Foundry, Azure ML, and AKS | Azure deployment matrix |
| [Day 7](day-07-adapter-lifecycle/README.md) | Adapter storage, loading, and rollback | Lifecycle and cache policy |
| [Day 8](day-08-benchmark-design/README.md) | Reproducible performance evaluation | Benchmark protocol |
| [Day 9](day-09-architecture-decision/README.md) | Architecture synthesis | Architecture decision record |
| [Day 10](day-10-final-review/README.md) | Final review and 30-day execution plan | Study packet and roadmap |

## Evidence levels

Use these labels consistently:

- **Confirmed:** Explicitly documented by an original paper, source code, versioned release note, model card, or official product documentation.
- **Observed:** Reproduced in a controlled experiment with versions and configuration recorded.
- **Implementation-specific:** True only for a named runtime, backend, model profile, or release.
- **Version-dependent:** Expected to change; a version and access date are mandatory.
- **Inferred:** Reasonable conclusion assembled from multiple sources but not stated directly.
- **Unverified:** No adequate evidence yet.
- **Contradicted:** Reliable evidence disproves the claim for the tested scope.

## Non-negotiable distinctions

Keep these concepts separate throughout the study:

1. A runtime supporting LoRA does not mean every model profile supports LoRA.
2. NIM supporting multi-LoRA does not prove that a particular Nemotron NIM profile supports it.
3. Microsoft Foundry managed compute adapter deployments and a NIM container on a managed online endpoint are different product paths.
4. A fully managed endpoint is not necessarily a serverless, pay-per-token service.
5. Foundry-created adapter support does not automatically imply bring-your-own externally trained adapter support.
6. API compatibility does not imply equivalent batching, cache, or hot-loading semantics.

## Materials

- `papers/` contains open-access papers downloaded from author or arXiv sources.
- [Source catalog](sources/README.md) identifies authoritative documentation and version-sensitive references.
- Each daily guide includes the minimum reading order and questions to answer.
- Templates are embedded in each day so the study can be completed without another planning system.

## Companion workshop

Use the [email Multi-LoRA workshop](../workshops/email-multilora/README.md) alongside Days 2, 4, 7, and 8. Its three notebooks implement multi-label data preparation, four independently trained adapters, text-only routing, held-out evaluation, and optional static vLLM serving. It uses a small Qwen base for accessibility and does not imply Nemotron/NIM support.
