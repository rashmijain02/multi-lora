# Current-agent manual response dataset

This directory contains the completed, manually authored dataset produced by the current chat agent.
No local language model, external endpoint, Python response generator, or persona template
generator authors the response text.

## Target

- Source emails: 2,103
- Assistants: ten fictional personas plus one generic baseline
- Final authored replies: 23,133

Each final persona CSV has exactly the source schema plus one column:

```text
id
split
subject
body
labels_json
label_count
dataset
dataset_revision
personality_response
```

## Authorship and assembly

Responses were authored from each source email and the corresponding persona specification.
Temporary batch ledgers were used during generation and deleted after the final CSVs passed
coverage and source-preservation checks.

Mechanical CSV assembly is allowed only to avoid manually copying the same source email body
eleven times. It does not generate, select, paraphrase, or modify reply text.

`MANIFEST.json` records provenance, validation results, response statistics, file sizes, and
SHA-256 checksums for the committed CSVs.

## Persona source

The behavioral source of truth is `../personalities/*.md`. The generic assistant is a neutral,
non-personalized control.

## Status

All persona datasets are complete:

- Maya Chen (CEO): 2,103 of 2,103.
- Daniel Okafor (CFO): 2,103 of 2,103.
- Priya Raman (L1 Customer Support Specialist): 2,103 of 2,103.
- Lucas Silva (Software Engineer): 2,103 of 2,103.
- Amina Yusuf (Sales Account Executive): 2,103 of 2,103.
- Jordan Lee (People Operations Manager): 2,103 of 2,103.
- Elena Petrova (Marketing Director): 2,103 of 2,103.
- Marcus Green (Legal and Compliance Counsel): 2,103 of 2,103.
- Sofia Alvarez (Business Operations Manager): 2,103 of 2,103.
- Noah Williams (Executive Assistant and Travel Coordinator): 2,103 of 2,103.
- Generic Assistant baseline: 2,103 of 2,103.

All eleven assistant datasets are complete: 23,133 manually authored responses across 2,103
source emails.
