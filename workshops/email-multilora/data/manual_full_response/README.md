# Current-agent manual response dataset

This directory is a resumable, manually authored dataset produced by the current chat agent.
No local language model, external endpoint, Python response generator, or persona template
generator authors the response text.

## Target

- Source emails: 2,103
- Assistants: ten fictional personas plus one generic baseline
- Final authored replies: 23,133
- Batch size: ten source emails (final batch has three)
- Expected batches: 211

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

## Process

1. Read the next ten source emails.
2. Act as each persona and manually author one final reply per email.
3. Record those 110 replies in a batch response ledger.
4. Mechanically join the authored text to the unchanged source rows.
5. Validate row counts, source-value preservation, assistant coverage, and non-empty replies.
6. Update `progress.json`.

Mechanical CSV assembly is allowed only to avoid manually copying the same source email body
eleven times. It does not generate, select, paraphrase, or modify reply text.

## Persona source

The behavioral source of truth is `../personalities/*.md`. The generic assistant is a neutral,
non-personalized control.

## Status

See `progress.json`. This dataset is incomplete until all 211 batches are recorded as complete.

`completed_source_rows` counts the contiguous source rows completed for **every** assistant. When
one persona advances independently, `persona_completed_source_rows` records that persona's
position without incorrectly marking the full eleven-assistant batch complete.

Current persona coverage:

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
