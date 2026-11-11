# Multi-LoRA Serving Study

An artifact-driven, ten-day study of multi-LoRA serving engines, NVIDIA NIM and Nemotron compatibility, and deployment choices on Microsoft Azure.

## Learning path

Work through the stages in order. Each stage produces something the next one uses.

| Stage | What you do | Uses from earlier stages | Hardware |
|-------|-------------|--------------------------|----------|
| 1. Concepts | Study kit and papers | — | Laptop |
| 2. Workshop 1, part A | Train and compare classification adapters | Stage 1 concepts | CPU is enough for the 0.5B default; a GPU is faster |
| 3. Workshop 1, part B | Train and evaluate persona reply adapters | Stage 2 environment | GPU recommended |
| 4. Workshop 2 | Run PersonaDesk persona agents on Hermes | Persona adapters from stage 3 as its writer (optional at first) | CPU with a hosted model; GPU for the full local stack |
| 5. Workshop 3 (optional) | Train a small model to take over one hosted agent role (the router), behind a parity gate | PersonaDesk checks, fixtures and cost model from stage 4; the 0.5B LoRA recipe from stage 2 | A 10 GB NVIDIA GPU (light tier) or a DGX Spark |
| 6. Workshop 4 (optional) | Let a Hermes agent run guarded training experiments (AutoResearch) | Hermes concepts and the "agent never grades itself" rule from stage 4 | A 10 GB NVIDIA GPU (light tier) or a DGX Spark |
| 7. Workshop 5 (optional) | Give each persona a personalised, read-only Workbench in Hermes WebUI (extension on our fork) | PersonaDesk personas, jobs and drafts from stage 4 | CPU is enough for what is built so far |
| 8. Workshop 6 (optional) | Evaluate Hermes agents with Vally: pass/fail release gates per persona and for safety | PersonaDesk driver, fixtures and guard from stage 4 | CPU with fake Hermes; a hosted model for real runs |
| 9. Decide | Choose a serving engine and an Azure path | Evidence from stages 1–8 | — |

To browse every workshop in one place (summaries, docs, commands, and starter prompts), open the
[UX workspace](ux-workspace/README.md): the **Workshop Hub** inside Hermes WebUI on our fork.

Workshop documentation lives in `docs/<workshop-id>/`, one folder per workshop.
Code, notebooks, configuration, and runtime prompt/policy files stay under `workshops/`.

### Stage 1: Concepts (study kit)

1. Read the [master plan](docs/multi-lora-learning-plan.md).
2. Follow the [10-day study kit](curriculum/README.md).
3. Use the [source catalog](curriculum/sources/README.md) for current official documentation.
4. Read the foundational papers in the [local paper library](curriculum/papers/README.md).
5. Copy the reusable worksheets from [`curriculum/templates/`](curriculum/templates/).

### Stages 2–3: Workshop 1, email Multi-LoRA

[`workshops/email-multilora`](docs/email-multilora/README.md) uses the public
`imnim/multiclass-email-classification` dataset and keeps its real multi-label structure. You
train a generalist plus operations, finance, and travel LoRA adapters on the default Qwen2.5 0.5B
base, or another verified profile at 8B or below. You then compare a lexical baseline, the base
model, the generalist, the specialists, and learned routing.

Part A, classification adapters:

- [01: Data audit and routing](workshops/email-multilora/notebooks/01_email_data_and_routing.ipynb)
- [02: Train and inspect adapters](workshops/email-multilora/notebooks/02_train_email_adapters.ipynb)
- [03: Evaluate and serve](workshops/email-multilora/notebooks/03_compare_and_serve.ipynb)

Part B, per-persona reply adapters (these become PersonaDesk's writers in stage 4):

- [04: Select persona response data](workshops/email-multilora/notebooks/04_persona_response_data.ipynb)
- [05: Train one persona adapter](workshops/email-multilora/notebooks/05_train_persona_adapter.ipynb)
- [06: Compare persona replies and serve](workshops/email-multilora/notebooks/06_compare_persona_responses.ipynb)
- [07: Exhaustive persona evaluation techniques](workshops/email-multilora/notebooks/07_persona_evaluation_techniques.ipynb)

Support material: the [code companion](docs/email-multilora/CODE_COMPANION.md) and the
[facilitator guide](docs/email-multilora/FACILITATOR.md).

### Stage 4: Workshop 2, PersonaDesk agents on Hermes

[`workshops/personal-agent-multilora`](docs/personal-agent-multilora/README.md) runs one
email assistant per persona on **Hermes Agent**. It uses:

- a Hermes profile per persona;
- the PersonaDesk plugin, which provides persona-scoped tools, a guard hook, and deterministic
  policy checks;
- persona LoRA writers from stage 3;
- human review of every draft, so nothing is ever sent;
- a local-only mail simulator (`pd-mail`) for realistic inbox practice.

Read in this order:

1. [User guide](docs/personal-agent-multilora/USER_GUIDE.md): set up your machine and
   get to your first reviewed draft. Start here; no GPU is needed.
2. [Simulated corporation guide](docs/personal-agent-multilora/SIMULATED_CORP_GUIDE.md):
   turn that setup into a fake company with 13 mailboxes, Thunderbird, scripted stories, and a
   measured hill-climbing loop for improving the assistants.
3. [Learning plan](docs/personal-agent-multilora/LEARNING_PLAN.md): the concepts, phase by
   phase.
4. [Proposal](docs/personal-agent-multilora/PROPOSAL.md): the full design. It includes a V2
   plan for Azure Foundry hosting and the CLM classification extension.
5. [DGX Spark guide](docs/personal-agent-multilora/DGX_SPARK_GUIDE.md): the full local
   GPU stack, with a vLLM controller, Multi-LoRA writers, and the CLM classifier.
6. [Email playground proposal](docs/personal-agent-multilora/EMAIL_PLAYGROUND_PROPOSAL.md):
   an optional richer mailbox (Stalwart/JMAP) for later phases.

### Stage 5: Workshop 3, small task models

[`workshops/slm-task-models`](docs/slm-task-models/README.md) asks whether a small model
trained for one narrow task can replace the hosted frontier model on that task. The first role is
the **router**, which picks the PersonaDesk policy checks an email needs. You build:

- a synthetic teacher dataset with a held-out test split;
- a TF-IDF baseline;
- a Qwen2.5-0.5B LoRA student on a 10 GB GPU;
- a hash-locked parity gate that every independent training run must pass.

Start with the [plan](docs/slm-task-models/PLAN.md). The measured rounds are in the
[evidence report](docs/slm-task-models/evidence/ROUTER_PARITY.md). The judge and the
controller are planned next.

### Stage 6: Workshop 4, AutoResearch

[`workshops/autoresearch-spark`](docs/autoresearch-spark/README.md) runs Karpathy's
autoresearch loop with Hermes as the agent and a guard-rail harness as the grader. The agent edits
only `train.py`. The metric is hash-locked, and each change is kept or reverted on a fixed time
budget. A held-out test checks the final result. There are two tiers:

- a **light tier** for a 10 GB consumer GPU with TinyStories, measured on an RTX 3080;
- a **DGX Spark tier**.

Start with the [plan](docs/autoresearch-spark/PLAN.md).

### Stage 7: Workshop 5, PersonaDesk Portal

[`workshops/persona-portal`](docs/persona-portal/README.md) gives each persona a
**Workbench** beside Hermes WebUI's own chat: work queue, drafts awaiting review, and their
evidence, laid out per persona from `ux/<persona-id>.json`. It is a WebUI extension on our fork
([`external/hermes-webui`](external/hermes-webui), branch `personadesk-portal`, now included in
`multilora-ux`). The extension is
backed by a read-only, single-persona sidecar behind WebUI's token-checked proxy. Built so far:
layouts, sidecar, extension, and an end-to-end smoke test. The model gateway and the portal are
planned. Start with the [plan](docs/persona-portal/PLAN.md).

### Stage 8: Workshop 6, evaluating agents with Vally

[`workshops/agent-evals-vally`](docs/agent-evals-vally/README.md) writes Microsoft Vally
eval specs for PersonaDesk. A custom executor drives a Hermes job; hidden answer keys and a
program grader check the stored draft; and a safety suite acts as a release blocker, with a
negative control that must fail. Everything runs with fake Hermes on a CPU. Start with the
[plan](docs/agent-evals-vally/PLAN.md).

### Stage 9: Decide

Use the study-kit templates and the evidence from the workshops to make the decisions listed
under [Intended result](#intended-result). For managed hosting, see the email workshop's
[Azure deployment guide](docs/email-multilora/AZURE_DEPLOYMENT.md).

## Proposed research workshops

[Leadership Evidence Lab](docs/leadership-evidence-lab/PROPOSAL.md) proposes a
neuroscience-informed, Hugging Face-based workshop on whether communication contains
enough evidence for empathy, decision-process, and leadership-style inferences. It separates
personal-learning exercises from an approval-gated workplace validation study. Its
[workshop guide](docs/leadership-evidence-lab/README.md) starts with fictional
support conversations and adds [configurable three-task pipelines](docs/leadership-evidence-lab/EXPERIMENTS.md)
for GoEmotions emotion classification and EmpatheticDialogues response generation,
verified with small local GPU runs.
The later research phases remain proposed; this is not a validated employee-assessment tool.

[Change Assurance Lab](docs/change-assurance-lab/PROPOSAL.md) proposes research-backed
quality engineering for real SDLC workflows: a Hermes harness runs just-in-time counterexample
tests and bounded goal-oriented hill climbing, with independently checked patch behavior and
a local small-model selector. It includes recent research, eight labs, a fictional release
scenario, and unattended shadow-mode workflows under fixed budgets. It is not implemented
and does not authorize autonomous merges.

### Personal-learning publication policy

These proposed workshops are for personal, noncommercial learning, with code and learning
materials intended for a public GitHub repository. Prefer MIT, BSD, Apache-2.0, or
public-domain sources for the default exercises; keep noncommercial-only and
restricted-access sources in clearly labeled optional tracks.

MIT or an equivalent permissive license is the target for new original workshop code and
documentation, not a relicensing of third-party datasets, source code, papers, or models.
This statement does not itself license existing repository contents. Establish ownership
and add the applicable license notice before releasing new material; preserve upstream
licenses, attribution, and notices for any permitted redistribution.

Publish download instructions, pinned source manifests, original fictional fixtures, and
reviewed aggregate results by default. Keep downloaded corpora, sensitive text, raw logs,
and learned weights/adapters out of public artifacts unless a separate rights and privacy
review permits their release. Personal use does not waive access or redistribution terms.

## What is included

- a detailed guide for every day;
- concrete outputs and exit criteria;
- open-access copies of four foundational papers with SHA-256 checksums;
- current links to official engine, NVIDIA, Microsoft, and Azure documentation;
- templates for claims, evidence, experiments, decisions, and execution;
- explicit safeguards against conflating NIM runtime support, Nemotron model-profile support, and Microsoft Foundry native adapter deployment support.

## Intended result

At the end of the study, the repository should contain enough evidence to choose:

- a primary serving engine and Azure deployment path;
- a fallback path;
- an adapter storage and lifecycle design;
- a reproducible benchmark;
- a scoped verdict on the exact NIM/Nemotron configuration;
- a reviewable architecture decision and 30-day delivery roadmap.
