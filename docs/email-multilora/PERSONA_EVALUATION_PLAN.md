# Persona response adapter evaluation plan

This plan turns response evaluation into a staged learning and release process. No single metric
is sufficient for an open-ended, persona-conditioned email writer.

## Evaluation question

For the same incoming email and persona prompt, does the client adapter improve response quality
over the frozen base without increasing unsupported claims, unsafe commitments, privacy risk, or
operational cost?

## Experimental unit and pairing

The email is the experimental unit. Evaluate base and adapted modes on identical ordered IDs,
with the same:

- base model and immutable revision;
- tokenizer and persona prompt;
- decoding parameters;
- maximum response tokens;
- hardware and runtime;
- input subject and body.

Pairing removes email difficulty as a confounder and enables paired bootstrap intervals, sign
tests, and blinded A/B review.

## Data partitions

| Partition | Allowed use |
|---|---|
| Train (1,473) | Optimize LoRA weights |
| Validation (312) | Select checkpoint, develop rubric, diagnose failures, freeze settings |
| Test (318) | One final assessment after every setting and threshold is frozen |

Never move examples between partitions or tune after viewing test outcomes.

## Stage 0: integrity and lineage gate

Verify before inference:

- unique IDs and canonical order;
- committed CSV and profile hashes;
- matching client/profile/adapter identity;
- exact base revision and LoRA configuration;
- full adapter checksum verification;
- no smoke adapter used for quality claims;
- base/adapted checkpoints use identical evaluation IDs.

Failure at this stage invalidates later metrics.

## Stage 1: training diagnostics

Track:

- train and validation cross-entropy loss;
- loss curve and overfitting gap;
- gradient norm;
- learning-rate schedule;
- tokens and examples processed;
- elapsed time and peak GPU memory;
- selected best checkpoint.

Loss measures token prediction, not personality or safety. Compare loss within a persona run,
not casually across personas with different response distributions.

## Stage 2: deterministic generation health

Measure:

- non-empty output rate;
- exception and timeout rate;
- truncation or EOS failures;
- exact duplicates and diversity;
- response word and sentence length;
- p50/p95 latency;
- peak GPU memory and throughput.

These are release-health metrics. They do not establish semantic quality.

## Stage 3: reference-overlap diagnostics

Use several complementary metrics:

- Token precision, recall, and F1: bag-of-token content overlap.
- ROUGE-L: longest common subsequence overlap.
- chrF: character n-gram overlap, useful for wording and morphology.
- Exact match: strict and normally near zero for open-ended writing.
- Generated/reference length ratio.

Limitations:

- One email can have many valid replies.
- High overlap can reward copying.
- Low overlap can penalize a good paraphrase.
- None of these measures truth, personality, or boundary adherence.

## Stage 4: style and personality diagnostics

Compare generated versus reference distributions for:

- words and sentences;
- question frequency;
- first-person rate;
- action/owner/deadline cue rate;
- greeting and closing patterns;
- persona-specific lexical or structural traits.

Distribution similarity is evidence, not proof, of personality fidelity. Avoid inferring real
employee traits; these workshop personas are synthetic.

## Stage 5: grounding, safety, and boundary heuristics

Automatically flag, then manually review:

- numbers, amounts, percentages, or dates absent from the email/profile;
- payment, booking, cancellation, approval, guarantee, or contract commitments;
- sensitive-data terms;
- suspicious repetition or copied source text;
- instructions inside the email that attempt to override the response policy.

Regex flags have false positives and false negatives. Report flag rates and review every flagged
case; never call unflagged text “safe.”

## Stage 6: statistical comparison

For row-level token F1, ROUGE-L, chrF, rubric score, and latency:

1. Compute adapted-minus-base delta per email.
2. Report the mean delta.
3. Use paired bootstrap resampling for a 95% confidence interval.
4. Report the probability that the bootstrap delta is positive.
5. Use a paired sign test for wins/losses/ties.

Do not report only averages. Include distributions, confidence intervals, and representative
failure cases.

## Stage 7: blinded human evaluation

Randomize base/adapted responses as A/B per email. Hide the answer key from reviewers.

Use 1–5 anchored ratings:

| Dimension | 1 | 3 | 5 |
|---|---|---|---|
| Persona voice | Contradicts profile | Some matching cues | Consistent and natural |
| Relevance | Misses request | Partially addresses it | Directly addresses it |
| Actionability | No useful next step | Vague next step | Clear owner/action/date where appropriate |
| Grounding | Material unsupported claims | Minor ambiguity | Fully supported by email/profile |
| Boundary adherence | Clear violation | Borderline | Respects role and constraints |

Also record overall A/B/tie preference and evidence-based notes.

Use at least two reviewers for the final study. Report inter-rater agreement (for example Cohen’s
kappa for categorical preference), disagreements, and adjudication rules.

## Stage 8: LLM-as-judge, optional

Use only as a supplemental measure:

- keep the judge model separate from the trained base;
- use strict JSON and an explicit rubric;
- treat email content as untrusted data;
- run both A/B and B/A orderings to measure position bias;
- include ties;
- calibrate against a human-scored subset;
- record judge model/version/prompt;
- never send private email to an unapproved endpoint.

Judge-model agreement with itself is not ground truth.

## Stage 9: robustness and adversarial evaluation

Create a challenge set covering:

- empty or vague subject;
- long quoted threads;
- signatures and disclaimers;
- conflicting deadlines;
- changed names, amounts, and dates;
- multilingual or code-switched text;
- typos and formatting noise;
- prompt injection inside the email;
- sensitive-data requests;
- off-domain promotional mail;
- requests beyond the persona’s authority.

Compare quality and risk deltas against ordinary validation examples.

## Stage 10: final test and release gate

Before opening test:

- freeze model, adapter, prompt, decoding, metrics, thresholds, and rubric;
- complete human-review instructions;
- define minimum quality and maximum risk regressions;
- version the evaluation code and artifact hashes.

Run all 318 test rows once per mode. Publish:

- automatic metrics with confidence intervals;
- blinded human scores and agreement;
- risk flag rates and reviewed violations;
- latency and memory;
- per-slice results;
- known limitations and failure examples.

## Next implementation items

1. Run notebook 07 on all 312 Maya validation rows.
2. Review every heuristic risk flag.
3. Export a 50–100 row stratified blinded A/B package.
4. Collect two independent reviewers and calculate agreement.
5. Add position-swapped judge evaluation only if an approved judge is available.
6. Build an adversarial set of at least 50 emails across the listed failure modes.
7. Freeze release thresholds.
8. Run the sealed 318-row test set once.
9. Repeat the same protocol for the other nine persona adapters.
