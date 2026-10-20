# Multi-LoRA Serving Study

An artifact-driven, ten-day study of multi-LoRA serving engines, NVIDIA NIM and Nemotron compatibility, and deployment choices on Microsoft Azure.

## Start here

1. Read the [master plan](docs/multi-lora-learning-plan.md).
2. Follow the [10-day study kit](curriculum/README.md).
3. Use the [source catalog](curriculum/sources/README.md) for current official documentation.
4. Read the foundational papers from the [local paper library](curriculum/papers/README.md).
5. Copy the reusable worksheets from [`curriculum/templates/`](curriculum/templates/).
6. Run the [hands-on email Multi-LoRA workshop](workshops/email-multilora/README.md): three notebooks for multi-label classification plus three notebooks for per-client persona response adapters.

## Hands-on workshop

The [email workshop](workshops/email-multilora/README.md) uses the public `imnim/multiclass-email-classification` dataset, preserving its actual multi-label structure. Train a generalist plus operations, finance, and travel LoRA adapters on the accessible default Qwen2.5 0.5B base—or another verified profile at 8B or below—and compare a lexical baseline, the base model, the generalist, all specialists, and learned routing.

- [01: Data audit and routing](workshops/email-multilora/notebooks/01_email_data_and_routing.ipynb)
- [02: Train and inspect adapters](workshops/email-multilora/notebooks/02_train_email_adapters.ipynb)
- [03: Evaluate and serve](workshops/email-multilora/notebooks/03_compare_and_serve.ipynb)
- [04: Select persona response data](workshops/email-multilora/notebooks/04_persona_response_data.ipynb)
- [05: Train one persona adapter](workshops/email-multilora/notebooks/05_train_persona_adapter.ipynb)
- [06: Compare persona replies and serve](workshops/email-multilora/notebooks/06_compare_persona_responses.ipynb)
- [07: Exhaustive persona evaluation techniques](workshops/email-multilora/notebooks/07_persona_evaluation_techniques.ipynb)
- [Facilitator guide](workshops/email-multilora/FACILITATOR.md)

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
