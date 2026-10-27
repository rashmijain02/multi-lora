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
| 5. Decide | Choose a serving engine and an Azure path | Evidence from stages 1–4 | — |

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

### Stage 5: Decide

Use the study-kit templates and the evidence from both workshops to make the decisions listed
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
