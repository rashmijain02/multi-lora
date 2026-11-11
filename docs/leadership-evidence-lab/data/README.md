# Fictional support exchanges

`workshops/leadership-evidence-lab/data/fictional_support.jsonl` contains original,
invented examples for personal learning.
No messages are copied from EPITOME, Reddit, TalkLife, employees, or clinical records.
Every character and situation is fictional. These are annotated teaching fixtures, not
validated psychometric ground truth or advice intended for actual support recipients.

## Annotation intent

The three dimensions follow the *names and broad communication concepts* studied by
[Sharma et al. (2020)](https://arxiv.org/abs/2009.08441):

- **Emotional reactions:** expressing warmth, concern, or recognition of feelings.
- **Interpretations:** conveying understanding or a tentative perspective grounded in
  what the speaker said, without unsupported assumptions.
- **Explorations:** inviting the speaker to elaborate through relevant questions.

For these fixtures, `0` means absent, `1` limited, and `2` explicit/strong expression.
This is a simplified author-created rubric. It is not a claim of annotation equivalence
to the original research protocol. More questioning is not automatically more helpful.
Zero on one mechanism is not evidence that the author lacks empathy.

Evidence rationales refer to exact substrings of the fictional response. The
language-model task generates mechanism scores, rationales, and evidence spans.
Exact membership checks do not establish that a rationale semantically supports its
score; do not present this as a reproduced rationale-extraction research model.

Scenario families remain wholly within one train/validation/test split. Related examples
and response variants are not independent people. Lexical overlap may still make this
small artificial task easy; report that limitation alongside all scores.

## Publication boundary

The fictional fixtures are intended as redistributable original workshop material.
No third-party conversation license is being transferred or replaced. Apply the project's
chosen license to original contributions only after establishing the relevant rights.
Keep model caches, training checkpoints, raw predictions, and notebook outputs local by
default; publish only reviewed aggregate findings.

## Separate public-data tasks

[The shared experiment workflow](../EXPERIMENTS.md) can explicitly download and prepare
GoEmotions emotion labels and EmpatheticDialogues listener responses. These live in
ignored workshop `data/external/` and `data/prepared/` folders, not in this fictional
JSONL file. Their schemas, licenses, and evaluation tasks remain distinct; no real
conversation is relabeled fictional or assigned invented empathy ground truth.
