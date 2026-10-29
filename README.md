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
| 7. Decide | Choose a serving engine and an Azure path | Evidence from stages 1–6 | — |

### Stage 1: Concepts (study kit)

1. Read the [master plan](docs/multi-lora-learning-plan.md).
2. Follow the [10-day study kit](curriculum/README.md).
3. Use the [source catalog](curriculum/sources/README.md) for current official documentation.
4. Read the foundational papers in the [local paper library](curriculum/papers/README.md).
5. Copy the reusable worksheets from [`curriculum/templates/`](curriculum/templates/).

### Stages 2–3: Workshop 1, email Multi-LoRA

[`workshops/email-multilora`](workshops/email-multilora/README.md) uses the public
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

Support material: the [code companion](workshops/email-multilora/docs/CODE_COMPANION.md) and the
[facilitator guide](workshops/email-multilora/FACILITATOR.md).

### Stage 4: Workshop 2, PersonaDesk agents on Hermes

[`workshops/personal-agent-multilora`](workshops/personal-agent-multilora/README.md) runs one
email assistant per persona on **Hermes Agent**. It uses:

- a Hermes profile per persona;
- the PersonaDesk plugin, which provides persona-scoped tools, a guard hook, and deterministic
  policy checks;
- persona LoRA writers from stage 3;
- human review of every draft, so nothing is ever sent;
- a local-only mail simulator (`pd-mail`) for realistic inbox practice.

Read in this order:

1. [User guide](workshops/personal-agent-multilora/docs/USER_GUIDE.md): set up your machine and
   get to your first reviewed draft. Start here; no GPU is needed.
2. [Simulated corporation guide](workshops/personal-agent-multilora/docs/SIMULATED_CORP_GUIDE.md):
   turn that setup into a fake company with 13 mailboxes, Thunderbird, scripted stories, and a
   measured hill-climbing loop for improving the assistants.
3. [Learning plan](workshops/personal-agent-multilora/LEARNING_PLAN.md): the concepts, phase by
   phase.
4. [Proposal](workshops/personal-agent-multilora/PROPOSAL.md): the full design. It includes a V2
   plan for Azure Foundry hosting and the CLM classification extension.
5. [DGX Spark guide](workshops/personal-agent-multilora/docs/DGX_SPARK_GUIDE.md): the full local
   GPU stack, with a vLLM controller, Multi-LoRA writers, and the CLM classifier.
6. [Email playground proposal](workshops/personal-agent-multilora/EMAIL_PLAYGROUND_PROPOSAL.md):
   an optional richer mailbox (Stalwart/JMAP) for later phases.

### Stage 5: Workshop 3, small task models

[`workshops/slm-task-models`](workshops/slm-task-models/README.md) asks whether a small model
trained for one narrow task can replace the hosted frontier model on that task. The first role is
the **router**, which picks the PersonaDesk policy checks an email needs. You build:

- a synthetic teacher dataset with a held-out test split;
- a TF-IDF baseline;
- a Qwen2.5-0.5B LoRA student on a 10 GB GPU;
- a hash-locked parity gate that every independent training run must pass.

Start with the [plan](workshops/slm-task-models/PLAN.md). The measured rounds are in the
[evidence report](workshops/slm-task-models/docs/evidence/ROUTER_PARITY.md). The judge and the
controller are planned next.

### Stage 6: Workshop 4, AutoResearch

[`workshops/autoresearch-spark`](workshops/autoresearch-spark/README.md) runs Karpathy's
autoresearch loop with Hermes as the agent and a guard-rail harness as the grader. The agent edits
only `train.py`. The metric is hash-locked, and each change is kept or reverted on a fixed time
budget. A held-out test checks the final result. There are two tiers:

- a **light tier** for a 10 GB consumer GPU with TinyStories, measured on an RTX 3080;
- a **DGX Spark tier**.

Start with the [plan](workshops/autoresearch-spark/PLAN.md).

### Stage 7: Decide

Use the study-kit templates and the evidence from the workshops to make the decisions listed
under [Intended result](#intended-result). For managed hosting, see the email workshop's
[Azure deployment guide](workshops/email-multilora/docs/AZURE_DEPLOYMENT.md).

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
