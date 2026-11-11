# Nemotron Nano 8B LoRA and Multi-LoRA findings

Verified against NVIDIA and Hugging Face documentation on 2026-10-19.

## Decision

The local workshop defaults to `qwen2.5-0.5b`.

`nemotron-nano-8b` remains a pinned optional profile for NVIDIA-specific experiments. Do not
treat the Qwen default as a statement that Nemotron cannot use LoRA. The choice keeps the default
exercise reliable on modest local hardware while preserving a documented upgrade path.

## What NVIDIA supports

NVIDIA NeMo Customizer explicitly lists Llama 3.1 Nemotron Nano 8B v1 with:

- LoRA training on 1x 80 GB GPU, tensor parallel size 1, pipeline parallel size 1.
- LoRA deployment through `nvcr.io/nim/nvidia/llm-nim:1.15.5` on 1x 80 GB GPU.

Source: [NVIDIA Llama Nemotron model support](https://docs.nvidia.com/nemo/microservices/26.3.1/customizer/models/llama-nemotron.html).

NVIDIA NIM supports:

- Static LoRA adapter discovery at startup.
- Dynamic adapter loading and unloading.
- Multiple loaded adapters, subject to GPU memory.
- Adapter selection through the request `model` field.
- `-feat_lora` profiles when a LoRA-capable profile is available for the selected model,
  image, and hardware.

Source: [NVIDIA NIM Fine-Tuning with LoRA](https://docs.nvidia.com/nim/large-language-models/latest/advanced-use-cases/finetune-lora.html).

Query the deployed NIM image's model/profile metadata before selecting
`NIM_MODEL_PROFILE`. Do not assume that a profile string exists for every image and GPU.

## Multi-LoRA meaning

Multi-LoRA serving loads several adapters against one exact base model and selects one adapter
for a request. It does not imply that several client adapters are merged or stacked in one
response.

All workshop client adapters intended for one server must share:

- Base model ID and immutable revision.
- Tokenizer and prompt contract.
- LoRA target modules and rank limits supported by the runtime.
- Compatible adapter format.

## Current RTX 3090 assessment

Observed workshop machine:

- NVIDIA GeForce RTX 3090.
- 24 GiB VRAM, with approximately 22.79 GiB free during inspection.
- CUDA compute capability 8.6.
- BF16 supported by the installed PyTorch CUDA runtime.

Nemotron Nano 8B has approximately 8.03 billion parameters:

- Raw BF16 base weights are approximately 14.96 GiB.
- Rank-8 LoRA weights on `q_proj` and `v_proj` are approximately 4.2 million parameters,
  or 16 MiB in FP32.

A tiny BF16 PEFT smoke run can fit, and a batch-one run with gradient checkpointing may fit.
However, a full 1,024-token BF16 run has limited headroom for activations, CUDA workspaces,
temporary buffers, and fragmentation. It is not the NVIDIA-certified 80 GB configuration.

For reliable full Nemotron training on 24 GiB, add and validate a QLoRA path:

- 4-bit NF4 base weights.
- BF16 compute.
- Double quantization.
- Gradient checkpointing.
- Memory-efficient attention where model/runtime compatibility is verified.
- Batch size 1 with gradient accumulation.

The workshop does not currently enable 4-bit QLoRA, so Nemotron full training is opt-in and
must begin with a smoke run. Qwen2.5 0.5B remains the safe default.

## Prompt contract

The Nemotron model card states that reasoning mode is controlled by the system message:

```text
system: detailed thinking off
```

It directs users to place all task instructions in the user message and recommends greedy
decoding for reasoning-off mode.

Source: [NVIDIA Nemotron Nano 8B model card](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Nano-8B-v1).

The current workshop prompts use ordinary instruct-model system messages. Before a real
Nemotron training run, implement one model-specific prompt contract and use it identically in
training, local inference, evaluation, vLLM, and NIM. Adapters trained with the earlier prompt
contract must not be silently reused.

## NIM lifecycle caveat

The older model-specific NGC container page is marked **End of Support**:
[Llama 3.1 Nemotron Nano 8B v1 NGC container](https://catalog.ngc.nvidia.com/orgs/nim/teams/nvidia/containers/llama-3.1-nemotron-nano-8b-v1).

For a supported NVIDIA workflow, use the versioned generic `llm-nim` image documented by the
current NeMo support matrix and verify profiles from the running environment. Do not depend on a
model-specific `:latest` image.
