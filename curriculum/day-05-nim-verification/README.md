# Day 5: Verify NVIDIA NIM and Nemotron Support

## Outcome

Produce a supportable answer to: "Can the exact Nemotron model serve the required adapters through NVIDIA NIM on the chosen Azure deployment path?"

## Rule for today

NIM-wide statements are not model-profile evidence. Confirm the exact combination:

```

## Verified starting point (2026-10-16)

Begin with these scoped facts, then recheck them against the release used in the lab:

- NVIDIA documents static and dynamic multi-LoRA for NIM LLM/VLM.
- NVIDIA documents custom adapters and adapters produced with NeMo or Hugging Face Transformers/PEFT for compatible NIM profiles.
- NIM requires a LoRA-capable model profile, typically identified by `-feat_lora`.
- No official source reviewed confirms multi-LoRA for an exact Nemotron NIM profile.
- Foundry native adapter deployments currently accept Foundry fine-tuning outputs, not imported external adapters.
- Official sources reviewed do not prove that NIM hosted through Foundry exposes all standalone NIM dynamic-loading controls.

These statements are deliberately different: NIM accepting custom adapters does not mean the Foundry native adapter-deployment control plane accepts them.text
NIM release
+ exact NIM model profile
+ exact base model revision
+ backend/profile
+ adapter format and rank
+ GPU/SKU
+ deployment path
= candidate supported configuration
```

## Step 1: Pin the candidate

Record:

- NIM container image and release;
- model/profile name;
- model and tokenizer revision;
- GPU model and count;
- deployment path: Foundry managed compute, Azure ML managed online endpoint, or AKS;
- NVIDIA AI Enterprise entitlement requirements;
- adapter training framework and versions.

## Step 2: Build an evidence hierarchy

Use evidence in this order:

1. exact model profile/model card and support matrix;
2. versioned NIM documentation and release notes;
3. container-generated model/profile metadata;
4. official NVIDIA examples for the same release;
5. source repository or issue confirmed by maintainers;
6. NVIDIA technical blog;
7. community report.

A general blog can generate a hypothesis, not close a compatibility question.

## Step 3: Verify adapter compatibility

Answer with citations:

- Which PEFT/NeMo adapter formats are accepted?
- Must adapters be trained from the identical base revision?
- Which target modules are supported?
- Are rank and dtype constrained?
- Can adapters be on local disk, object storage, or model registry?
- Are quantized base models compatible?
- Is adapter conversion required?
- Does the exact Nemotron profile advertise LoRA?

If the last question is unanswered, mark the architecture `blocked pending lab/vendor confirmation`.

## Step 4: Verify multi-LoRA semantics

Investigate separately:

- maximum adapters known to the service;
- GPU-resident adapters;
- CPU-resident adapters;
- concurrent adapters within one batch;
- startup-only loading versus runtime discovery;
- polling or refresh behavior;
- explicit load/unload APIs;
- eviction policy;
- behavior on a missing, corrupt, or incompatible adapter;
- replica consistency during refresh;
- rollback behavior.

Do not infer cache settings from another NIM release or backend.

## Step 5: Separate the Azure product paths

Create three columns:

1. **NIM deployed on managed compute:** managed GPU infrastructure and endpoint; runtime remains the NIM deployment.
2. **Foundry native adapter deployment:** registered Foundry fine-tuning output attached to a compatible LoRA-enabled base deployment template.
3. **NIM on AKS:** self-managed Kubernetes deployment with greater runtime/storage control.

For each capability, mark which path documents it. Never merge features across columns.

## Step 6: Answer the BYO question

For externally trained adapters, require explicit evidence that the selected path supports:

- importing/registering the artifact;
- validating it against the base;
- attaching or discovering it;
- serving it through the selected API;
- updating and rolling it back.

Current Foundry preview documentation limits native adapter deployments to Foundry fine-tuning outputs and says externally produced adapters cannot yet be imported. State that clearly. Do not assume NIM's standalone support for custom adapters overrides a managed service control plane or proves that the managed NIM endpoint exposes the required mounts, watcher, or load/unload API.

## Step 7: Prepare a minimal proof

Define a lab with:

1. base-model request;
2. adapter A request;
3. adapter B request;
4. alternating A/B concurrent requests;
5. cold adapter C;
6. incompatible adapter rejection;
7. adapter update and rollback;
8. replica restart;
9. scale-out consistency.

Capture TTFT, throughput, memory, logs, HTTP status, and selected adapter identity.

## Deliverables

1. `nim-support-matrix.csv`
2. `nemotron-profile-card.md`
3. `managed-path-separation.md`
4. `nim-verification-memo.md`
5. `vendor-questions.md`

## Required conclusion format

```text
Verdict: Supported | Conditionally supported | Not supported | Unverified
Exact scope:
Evidence:
Excluded interpretations:
Remaining proof:
Architecture impact:
```

## Exit check

- [ ] NIM release, profile, model revision, and GPU are pinned.
- [ ] Nemotron-specific evidence exists or the verdict is unverified.
- [ ] Multi-LoRA, hot loading, and cache behavior are individually assessed.
- [ ] Foundry native adapters and NIM-managed endpoints are not conflated.
- [ ] External adapter import is not claimed without explicit evidence.
- [ ] A minimal reproduction can falsify the proposed configuration.
