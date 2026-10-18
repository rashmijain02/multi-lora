# Source Catalog

Last verified: **2026-10-16**

This catalog prioritizes original papers, official documentation, official repositories, model cards, and release notes. Pages labeled **version-sensitive** must be rechecked when executing the lab or making a production decision.

## Foundations and papers

| Source | Use | Stability |
|---|---|---|
| [LoRA paper](https://arxiv.org/abs/2106.09685) | Mathematical and training foundation | Stable, local PDF included |
| [PetS paper](https://arxiv.org/abs/2203.04810) | Parameter-efficient transformer serving | Stable, local PDF included |
| [Punica paper](https://arxiv.org/abs/2310.18547) | Segmented-gather kernels and multi-tenant LoRA serving | Stable, local PDF included |
| [S-LoRA paper](https://arxiv.org/abs/2311.03285) | Unified paging, scheduling, and high adapter scale | Stable, local PDF included |
| [S-LoRA project overview](https://lmsys.org/blog/2023-11-15-slora/) | Accessible architecture overview | Stable explanation; paper is authoritative |
| [Hugging Face PEFT LoRA guide](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora) | Adapter format and PEFT concepts | Version-sensitive |
| [PEFT checkpoint format](https://huggingface.co/docs/peft/en/developer_guides/checkpoint) | `adapter_config.json`, adapter weights, and checkpoint semantics | Version-sensitive; pin the PEFT release |
| [Safetensors documentation](https://huggingface.co/docs/safetensors/en/index) | Safe tensor serialization | Stable concept; library evolves |
| [Hugging Face pickle scanning](https://huggingface.co/docs/hub/en/security-pickle) | Security rationale and scanning limits for pickle-based artifacts | Security guidance; do not treat scanning as a complete trust control |

## Open-source serving engines

| Source | What it establishes | Important caution |
|---|---|---|
| [vLLM stable LoRA docs](https://docs.vllm.ai/en/stable/features/lora/) | Per-request adapters, serving flags, and runtime loading APIs | Runtime updating carries an explicit production security warning; pin a release |
| [vLLM repository](https://github.com/vllm-project/vllm) | Source, releases, supported-model implementation | Repository `main` is not a released version |
| [SGLang LoRA serving](https://docs.sglang.io/advanced_features/lora.html) | Mixed-adapter batching, cache controls, backends, dynamic loading | Defaults and backends are version-sensitive |
| [SGLang repository](https://github.com/sgl-project/sglang) | Source and releases | Verify exact target architecture |
| [LoRAX repository](https://github.com/predibase/lorax) | Dynamic adapter loading, heterogeneous batching, deployment artifacts | Product claims require target-specific validation |
| [LoRAX documentation](https://loraexchange.ai/) | Base-model and adapter support, guides | Verify maintenance and release state |
| [TGI LoRA documentation](https://huggingface.co/docs/text-generation-inference/en/conceptual/lora) | Multi-adapter startup loading and request selection | Documentation identifies the feature as evolving |
| [TGI repository](https://github.com/huggingface/text-generation-inference) | Source and releases | Pin release and architecture |

## NVIDIA NIM and TensorRT-LLM

| Source | What it establishes | Important caution |
|---|---|---|
| [NIM LoRA documentation](https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/finetune-lora.html) | Static and dynamic LoRA modes, `NIM_PEFT_SOURCE`, refresh polling, runtime APIs, and multiple adapters | Requires a LoRA-capable `-feat_lora` profile; this does not prove any particular Nemotron profile supports it |
| [NIM 1.12 PEFT documentation](https://docs.nvidia.com/nim/large-language-models/1.12.0/peft.html) | Version-pinned statement that NIM supports NeMo/Transformers adapters, dynamic multi-LoRA, and custom adapters | Useful historical/versioned evidence; do not apply it to another release without checking |
| [NIM model profiles](https://docs.nvidia.com/nim/large-language-models/latest/deployment/model-profiles-and-selection.html) | How to inspect and select model profiles | Must be checked inside the exact deployment/release |
| [NIM on Azure](https://docs.nvidia.com/nim/large-language-models/latest/deployment/csp-deployment/azure.html) | Two Azure paths: self-managed AKS and Foundry via Azure ML managed online endpoints | Managed endpoint is not synonymous with serverless API |
| [NIM multi-LoRA technical blog](https://developer.nvidia.com/blog/seamlessly-deploying-a-swarm-of-lora-adapters-with-nvidia-nim/) | Example implementation and motivation | Blog evidence is not a model support matrix |
| [NIM on Foundry technical blog](https://developer.nvidia.com/blog/accelerated-ai-inference-with-nvidia-nim-on-azure-ai-foundry/) | Managed-compute integration and deployment outline | Recheck current catalog, SKU, price, and profile |
| [TensorRT-LLM LoRA documentation](https://nvidia.github.io/TensorRT-LLM/advanced/lora.html) | TensorRT-LLM-specific LoRA implementation | Do not assume a NIM profile uses this backend |
| [TensorRT-LLM repository](https://github.com/NVIDIA/TensorRT-LLM) | Source and release notes | Backend capabilities are not automatically exposed by NIM |

## Nemotron verification

Nemotron is a model family, not one compatibility target. Start at:

- [NVIDIA model catalog](https://build.nvidia.com/models)
- [NVIDIA organization on Hugging Face](https://huggingface.co/nvidia)
- the exact NIM model/profile card presented by the intended deployment environment.

For the exact model, capture:

1. canonical model identifier and revision;
2. architecture and tokenizer;
3. NIM container release;
4. profile list from that container;
5. presence of a `-feat_lora` profile;
6. accepted adapter format, rank, target modules, and dtype;
7. GPU and parallelism requirements.

**Not established by a generic NIM LoRA page:** that every Nemotron model has a LoRA-capable NIM profile, that arbitrary externally trained adapters are supported by every managed control plane, or that backend/configuration details transfer across NIM releases.

## Microsoft Foundry and Azure

| Source | What it establishes | Important caution |
|---|---|---|
| [Foundry adapter deployment overview](https://learn.microsoft.com/azure/foundry/concepts/adapter-deployment-overview) | Shared target deployment, registered adapter, adapter deployment, and multi-LoRA concepts | Feature scope, compatible templates, and supported models are version-sensitive |
| [Foundry managed compute overview](https://learn.microsoft.com/azure/foundry/concepts/managed-compute-overview) | Managed runtime choices and responsibility boundary | Preview when verified; runtime listing does not prove every runtime supports every adapter feature |
| [Deploy LoRA adapters to managed compute](https://learn.microsoft.com/azure/foundry/how-to/deploy-lora-managed-compute) | Portal/API workflow and current prerequisites | Marked preview when verified; recheck external-adapter import rules |
| [Azure ML managed online endpoints](https://learn.microsoft.com/azure/machine-learning/concept-endpoints-online) | Managed endpoint concepts, traffic, and deployment behavior | Does not itself establish multi-LoRA support |
| [Azure ML custom container deployment](https://learn.microsoft.com/azure/machine-learning/how-to-deploy-custom-container) | Custom inference container path | Team owns runtime compatibility and image lifecycle |
| [AKS GPU workloads](https://learn.microsoft.com/azure/aks/use-nvidia-gpu) | GPU node support on AKS | SKU/region availability changes |
| [AKS workload identity](https://learn.microsoft.com/azure/aks/workload-identity-overview) | Identity-based Azure resource access | Requires cluster/application setup |
| [Azure Blob versioning](https://learn.microsoft.com/azure/storage/blobs/versioning-overview) | Immutable/versioned adapter storage building block | Design lifecycle and retention explicitly |
| [Azure architecture decision records](https://learn.microsoft.com/azure/well-architected/architect-role/architecture-decision-record) | ADR guidance | Use with measurable evidence |

## Benchmarking and observability

| Source | Use |
|---|---|
| [GenAI-Perf](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/perf_analyzer/genai-perf/README.html) | NVIDIA client benchmarking and LLM metrics |
| [vLLM benchmark CLI](https://docs.vllm.ai/en/latest/benchmarking/cli/) | Serving throughput/latency benchmark tooling; current docs recommend external GuideLLM for some workflows |
| [NIM LoRA benchmarking](https://docs.nvidia.com/nim/benchmarking/llm/latest/benchmarking-lora.html) | NVIDIA's concrete adapter benchmark workflow |
| [NVIDIA DCGM Exporter](https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/latest/dcgm-exporter.html) | GPU telemetry for Kubernetes |
| [Azure ML online endpoint monitoring](https://learn.microsoft.com/azure/machine-learning/how-to-monitor-online-endpoints) | Managed endpoint metrics and logs |

## Evidence gaps that require a lab or vendor confirmation

- Exact Nemotron NIM profile with LoRA capability.
- Compatibility of the actual externally trained adapter with that profile.
- Whether the intended Foundry managed deployment exposes all NIM dynamic-loading controls.
- Replica consistency and storage behavior for dynamic adapters on managed endpoints.
- Cold-load latency, cache capacity, and eviction under the target distribution.
- Regional quota and capacity for the selected GPU SKU.

## Verified support snapshot

The following is the narrow conclusion supported by official documentation checked on 2026-10-16:

| Question | Verdict | Scope |
|---|---|---|
| Does NIM LLM/VLM support multiple LoRA adapters? | **Yes, conditionally** | Static and dynamic modes are documented, but the selected model must expose a LoRA-capable `-feat_lora` profile. |
| Can standalone/self-managed NIM use externally trained adapters? | **Yes, conditionally** | NVIDIA documents NeMo and Hugging Face Transformers/PEFT adapters and custom adapter directories. Base-model identity and profile compatibility still apply. |
| Does the current Foundry native adapter-deployment feature accept externally trained adapters? | **No** | Current preview documentation says it applies only to adapters produced by Foundry fine-tuning and that importing your own adapters is not yet supported. |
| Does Foundry native managed compute support multi-LoRA? | **Yes, in its documented preview scope** | Multiple compatible Foundry adapter deployments can share one target deployment; current documentation states a limit of eight adapter deployments per target. |
| Is NIM multi-LoRA on a Foundry managed endpoint explicitly documented end to end? | **Unverified** | NIM is a managed-compute runtime and NIM supports LoRA generally, but official documentation reviewed does not establish that the Foundry NIM path exposes the complete multi-LoRA/dynamic-loading workflow. |
| Is an exact Nemotron NIM profile documented for multi-LoRA? | **Unverified** | No Nemotron-specific NIM multi-LoRA example or explicit support statement was found. Inspect the exact container's profile metadata and require a `-feat_lora` profile. |

The key architectural distinction is therefore:

```text
NIM runtime capability
!= exact Nemotron profile capability
!= Foundry native adapter-deployment capability
!= controls exposed by NIM when hosted through a managed endpoint
```
