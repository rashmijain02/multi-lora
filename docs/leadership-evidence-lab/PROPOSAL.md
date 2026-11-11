# Leadership Evidence Lab

## Can everyday communication support defensible leadership inferences?

**Status:** fictional-data initialization implemented alongside this proposal; later
research phases remain proposed. No real-person dataset collection or published-study
reproduction is claimed.
**Prepared:** 2026-11-09.
**Intended use:** personal, noncommercial learning, with public GitHub code and learning
materials under an intended MIT or equivalent permissive license for original contributions.
Third-party assets retain their own terms; follow the shared
[publication policy](../../README.md#personal-learning-publication-policy).
**Perspective:** cognitive neuroscience, psychometrics, and applied AI.
**Audience:** ML engineers, computational social scientists, organizational psychologists,
and research-minded leadership-development practitioners.
**Format:** six three-hour labs, following a facilitator preparation sprint; an optional
12-16-week research pilot follows ethics approval and recruitment.
**Recommendation:** build an evidence-and-abstention system, not an employee profiler.

## Initialization: fictional empathy-expression experiments

Begin with the [runnable workshop guide](README.md) and its three notebooks: data
understanding, manual training/testing, and evaluation. Use only original fictional
support exchanges, with author-assigned teaching labels and rationale spans for emotional
reactions, interpretations, and explorations. The design is inspired by the
[EPITOME research](https://github.com/behavioral-data/Empathy-Mental-Health), without
copying its Reddit/TalkLife conversations or claiming identical annotations or splits.

The initial experiments compare a lexical baseline, Qwen instruction inference, and
supervised Qwen LoRA. A local Qwen2.5-0.5B profile targets the inspected RTX 3080 10 GB.
Pinned Qwen2.5-7B and Llama-3.1-Nemotron-Nano-8B profiles prepare the same experiment for
a larger machine. A prepared profile is not an executed result. Nemotron has separate
NVIDIA/Llama terms; the repository's intended license does not override them.

This initialization teaches reproducible model experimentation, not real-world empathy
measurement. Training labels on fictional exchanges do not establish clinical validity,
leadership validity, or a reproduction of the published RoBERTa study.

Follow-on phases remain gated:

1. Complete and understand the fictional-data baseline and model comparisons.
2. Expand independent annotation, scenario diversity, and uncertainty/robustness testing.
3. Consider separately permitted public-data replication with its original protocol only
   if explicitly authorized; no automatic ingestion is part of this initialization.
4. Investigate leadership translation and independently consented workplace validation.
5. Add bounded Hermes experiment optimization after metrics and evaluation are reliable.

## 1. Executive proposal

The motivating question is:

> Do a person's emails and conversations alone contain enough evidence to infer
> decisiveness, expressed empathy, and decision style, and can those inferences support
> a defensible mapping into six leadership buckets?

This is a research question, not an established product capability. Language provides
observable behavior under particular circumstances. It does not directly measure a
person's internal state, brain function, stable character, or leadership effectiveness.

We propose two deliberately separate tracks:

1. **Workshop track:** use permissively licensed Hugging Face data and original fictional
   scenarios to learn annotation, evidence extraction, context-sensitive classification,
   calibration, and abstention. No real-person donations or restricted data are required.
2. **Research track:** test whether the same approach generalizes to voluntarily donated
   workplace communication, using independently collected psychometric and behavioral
   criteria. This track is approval-gated and is not required to complete the workshop.

**Working interpretation of "six leadership buckets":** Goleman's coercive/directive,
authoritative/visionary, affiliative, democratic, pacesetting, and coaching styles [S9].
The user has not supplied a taxonomy. This is a provisional design assumption, not a
claim that these are the intended buckets. Confirm the organization's exact definitions
before collecting leadership labels; if different, replace the mapping and revalidate it.

The central deliverable is a **context-bound evidence report**: supported observations,
counterevidence, missing opportunities to observe behavior, calibrated uncertainty, and
an explicit option to say "insufficient evidence." It is not a permanent person label.

### What success would and would not establish

- Success on public emotion or counseling data establishes performance on those tasks.
- Success on fictional workplace scenarios establishes pipeline behavior, not validity
  for real people.
- Success against independent workplace criteria may establish a bounded association
  for the sampled population, communication setting, and observation window.
- None of these alone establishes causation, neurological measurement, leadership
  effectiveness, or suitability for employment decisions.

## 2. Scientific motivation and novelty

There is already evidence that language contains some personality-relevant information.
Peters and Matz report mean correlation of `r = 0.29` between LLM estimates and
self-reported Big Five scores from Facebook status updates, alongside uneven accuracy
across demographic groups [S6]. This is neither 29% classification accuracy nor evidence
that a model can assess an individual reliably.

A separate conversational study reports different mean correlations for deliberately
elicited personality information (`r = .443`), more naturalistic interaction (`r = .218`),
and a helpful-assistant condition (`r = .117`) [S7]. These are study-specific results from
the cited preprint, not expected workshop performance. They motivate a key distinction:
**eliciting diagnostic evidence is not the same as finding it in ordinary work messages.**

Consequently, "an LLM predicts personality from text" is not a sufficient novelty claim.
A potentially publishable contribution would combine:

1. **Ecological validity:** naturally occurring, consented workplace communication rather
   than personality-eliciting interviews alone.
2. **Construct validity:** separate expressed empathy, decision-process behavior, stable
   traits, and situational leadership styles instead of treating them as synonyms.
3. **Evidence sufficiency:** quantify how much independent text and context are needed,
   when predictions become unstable, and when abstention is appropriate.
4. **Incremental validity:** compare with role, activity, lexical, and context baselines;
   show what text contributes beyond obvious workplace confounds.
5. **Leadership translation:** validate, rather than assume, the additional mapping from
   observed behavior to the six styles.
6. **Boundary conditions:** report domain shift, missing evidence, stereotype sensitivity,
   and null results as primary scientific findings.

No reviewed source establishes the complete chain from operational emails to these six
styles. A focused literature review and novelty check remain prerequisites to a paper.

## 3. Neuroscience alignment: useful theory, strict limits

The workshop is **neuroscience-informed computational behavioral research**, not a
neurodiagnostic system. It contains no neural recordings.

| Scientific distinction | AI operationalization | Inference we must not make |
|---|---|---|
| Cognitive perspective-taking, affect sharing, and compassionate action are related but distinct; empathy is not a single scalar [S10] | Separately annotate acknowledgment, perspective-checking, exploratory questions, and offered support | Warm wording proves felt empathy, compassion, or a particular neural activation |
| Decision behavior involves evidence quality, thresholds, uncertainty, and speed-accuracy tradeoffs [S11] | Detect alternatives, requested evidence, explicit commitments, conditions for revision, and recorded decision opportunities | Short email latency is a neural decision threshold, or fast action is necessarily good judgment |
| A stable disposition is not identical to a transient state or a role-constrained response | Compare the same consenting participant across time, channels, counterpart roles, and task contexts | One crisis message or one polite reply reveals a stable trait |
| Leadership can be situational and flexible [S9] | Model style evidence at the episode level before any longitudinal aggregation | Each person belongs permanently to exactly one bucket |

Use the following as a **conceptual measurement model**, not an identified causal model:

`observed communication = person + situation + role + audience + channel + assistance + noise`

In the research extension, compare person-level and context-level variation with a
hierarchical model. Role, workload, opportunity to act, and message selection can be
confounded; a random intercept does not remove all such confounding.

Optional decision tasks may collect choices and response times under controlled evidence
conditions. A diffusion model requires suitable repeated trials and a defensible task
design [S11]; it cannot be fitted meaningfully to ordinary email timestamps as though they
were laboratory reaction times. EEG/fMRI is outside scope. A future neural study would
need separate hypotheses, equipment, expertise, approval, and validation.

## 4. Construct map and annotation rubric

The prediction unit is a **speaker's contribution to a contextualized decision or support
episode**, not a sentence stripped of context. Preserve enough preceding dialogue to
identify who is responding to whom, while minimizing retained personal content.

| Construct | Observable evidence | Alternative explanation / counterevidence | Independent criterion for research |
|---|---|---|---|
| Expressed empathy | Acknowledges another's stated perspective; checks understanding; responds to the actual need | Stock courtesy, unsupported mind-reading, dismissive response after warm introduction | Independent observers of a separate collaborative task; approved self-report measures are secondary |
| Decisiveness | Makes a justified commitment when an opportunity exists; sets ownership and next step; revises when warranted | Job authority, deadline pressure, premature closure, someone else's decision | Predefined decision tasks scored for commitment, appropriateness, and calibrated revision, not speed alone |
| Decision style | Requests evidence, compares alternatives, seeks advice, states intuition, postpones, or acts immediately | Missing context, mandatory approval, unavailable information, organizational constraints | General Decision-Making Style framework [S12], subject to instrument permissions, plus independent task behavior |
| Leadership-style expression | Pattern of directing, aligning, consulting, supporting, setting standards, or developing others | Role mandate, boilerplate, selective examples, temporary crisis | Blinded episode ratings and separate simulation/observer criteria under a fixed six-style rubric |
| Big Five traits, exploratory only | Aggregated language features over independent episodes | Topic, occupation, culture, selective self-presentation, assistant-written text | A specified public-domain IPIP scale with its scoring key [S8]; not an automatic proxy for leadership |

For each behavioral dimension use an ordinal rubric:

- `0`: not expressed despite a documented relevant opportunity.
- `1`: weak or ambiguous evidence.
- `2`: clear expression supported by a specific span.
- `3`: repeated or sustained expression within the episode.
- `not_observable`: no relevant opportunity, missing context, or unreliable authorship.

`not_observable` is not zero. Missing empathy evidence is not proof of low empathy.
Code counterevidence separately; preserve legitimate disagreement rather than manufacture
consensus. Require at least two trained annotators per research evaluation episode, blinded
to questionnaires, participant identity where feasible, and model outputs.

### Provisional six-style mapping

These are **testable rubric hypotheses**, not a validated psychometric conversion.
Scores are non-exclusive: they need not sum to one, and multiple or no styles may apply.

| Provisional style | Candidate evidence pattern | Disconfirming or missing evidence |
|---|---|---|
| Coercive / directive | Explicit instructions, immediate compliance expectations, narrow discretion | A single deadline or a necessary safety instruction is insufficient to characterize a person |
| Authoritative / visionary | Articulates direction and purpose while allowing discretion in execution | Authority title or confident tone without a shared direction |
| Affiliative | Repairs relationships, recognizes strain, prioritizes connection | Courtesy without responsive relational behavior |
| Democratic | Invites substantive input and visibly incorporates it into a decision | Asking for opinions after the decision is already fixed |
| Pacesetting | Establishes demanding standards and models or closely monitors execution | High message volume or urgency alone |
| Coaching | Elicits development goals, gives individualized feedback, follows up on learning | Generic advice or counseling-style language without development context |

Do not hardcode `empathy -> affiliative` or `decisiveness -> directive`. Keep a direct
episode-to-style baseline and a behavior-mediated model; compare both against independent
labels. Good empathy classification does not validate the leadership mapping.

## 5. Dataset plan: Hugging Face plus original research sources

**Publicly downloadable is not synonymous with open-source, unrestricted, or consented
for employee profiling.** The following is a source review as of 2026-11-09, not legal
clearance. No datasets were downloaded for this proposal. Pin exact revisions and review
the original license, provenance, sensitive content, and downstream model obligations
before a facilitator admits a dataset.

| Dataset and verified entry point | Actual supervision / unit | Appropriate workshop use | Access and limitations |
|---|---|---|---|
| [GoEmotions on Hugging Face](https://huggingface.co/datasets/google-research-datasets/go_emotions) [S1] | Reddit comments with 27 emotion categories plus neutral; simplified splits contain 43,410 / 5,426 / 5,427 examples | CPU multi-label baseline; teach why emotion recognition is not empathy or personality measurement | HF card declares Apache-2.0. Reddit language is not workplace language; raw configuration exposes author/thread metadata. Do not retain handles or build user profiles |
| [EmpatheticDialogues on Hugging Face](https://huggingface.co/datasets/facebook/empathetic_dialogues) [S2] | Contextualized conversations about emotional experiences; HF split counts are utterance rows, not independent people | Optional noncommercial, local-only extension: compare context with isolated turns and annotate a bounded response sample | CC BY-NC 4.0 is not a permissive MIT-equivalent license. Personal noncommercial use fits the intended use category, subject to all license terms. Keep the corpus out of the default public artifacts; do not relicense it as MIT. Emotion-context labels are not expert empathy or trait scores |
| [EPITOME / Empathy in Text-based Mental Health Support](https://github.com/behavioral-data/Empathy-Mental-Health) [S3] | Emotional reactions, interpretations, explorations, and evidence rationales on support post-response pairs | Literature reference by default; optional rationale benchmark only after access and reuse review | Repository makes the Reddit portion available, but its applicable reuse terms still require review. TalkLife requires separate permission even for personal noncommercial study. Neither is required; no sensitive raw examples in public artifacts |
| [AnnoMI original release](https://github.com/uccollab/AnnoMI) and [HF conversion](https://huggingface.co/datasets/to-be/annomi-motivational-interviewing-therapy-conversations) [S4] | 133 demonstration transcripts; original annotations include reflection/question/input behaviors, with richer labels in the full version | Optional study of observable conversational behaviors relevant to a coaching hypothesis | HF conversion declares `openrail`, but that is not proof of original data rights. Its chat formatting is not a substitute for expert labels. Hold until original terms are reconciled; use original annotations if admitted |
| [PANDORA paper](https://aclanthology.org/2021.socialnlp-1.12/) [S5] | Reddit users partially labeled for personality and demographics; paper reports about 10k users, about 1.6k with Big Five labels | Literature critique and optional approved secondary analysis of person-level splitting | Not a default hands-on dataset. Verify original access, label provenance, and license; self-disclosed labels and sensitive demographic fields are not independent workplace ground truth |
| [IPIP instruments](https://ipip.ori.org/) [S8] | Public-domain items and scales, not a paired email/personality dataset | Collect independent criteria in the approved research extension | Choose a named scale and correct scoring key. Public-domain items do not make participants' responses public; do not modify items and assume original validity |

### Recommended admission order

1. **Default permissive track:** GoEmotions for local emotion-classification experiments,
   plus newly authored fictional conversations for empathy-expression and decision-style
   exercises. Preserve Apache-2.0 obligations and source attribution. IPIP public-domain
   items may support measurement-design exercises without collecting anyone's responses.
2. **Original behavioral fixtures:** write explicit decision opportunities and contrasting
   responses, not paraphrases of restricted or sensitive records. Human-authored fixtures
   can be released under the chosen permissive license when rights are clear. Label any
   model-assisted fixtures and review the model/provider terms before publishing.
3. **Optional noncommercial track:** download EmpatheticDialogues locally after reviewing
   CC BY-NC 4.0. Publish the experiment recipe and reviewed aggregate metrics, not bundled
   source conversations by default. This is separate from the permissive core.
4. **Optional permission/terms-gated track:** EPITOME, TalkLife, AnnoMI, and PANDORA remain
   literature references unless their respective access, reuse, and privacy gates pass.
   Do not infer permission from a public mirror, a code license, or noncommercial intent.
5. **Optional research track:** prospectively consented workplace data plus independent
   criteria. No verified resource above supplies all of those labels together. This is
   unnecessary for personal learning and cannot be simulated into evidence of validity.

The permissive core therefore demonstrates the measurement pipeline, not a validated
empathy/personality model. GoEmotions remains an emotion dataset; original fictional
annotations are teaching labels, not evidence about real people's psychological traits.

### Public repository boundary

Publish original code/docs, dataset URLs and pinned revisions, attribution/license
records, download instructions, original fictional fixtures, and reviewed aggregate
results. Keep raw downloaded data local even when redistribution might be permitted;
this avoids unnecessary copies of personal text and makes source terms explicit.

Do not treat an MIT repository license as applying to dataset excerpts, annotations
containing source text, embeddings, or trained adapters. Review each artifact's source
licenses, model terms, and potential memorization/privacy risks before any release.
No automatic legal conclusion about trained weights is assumed. The default is to publish
training recipes and metrics, not checkpoints.

Add narrowly scoped cache/artifact ignores and a pre-publication check when implementing
the labs. Clear notebook outputs and inspect screenshots, generated reports, and example
logs for source text or identifiers; an ignored dataset directory alone is insufficient.

The reviewed public sources do **not** solve decisiveness or workplace leadership
measurement. That gap is part of the research contribution, not something to fill by
asking an LLM to invent "ground truth."

Exclude MBTI-to-Big-Five shortcuts, inferred clinical conditions, scraped employee
mailboxes, and Enron as a default person-level benchmark. Public corporate emails are
not automatically consented research records and do not supply validated trait labels.

### Dataset contract

For every admitted source, record upstream owner, URL, exact revision/checksum, license
text and approval status, collection context, unit of analysis, annotation provenance,
group identifiers, split policy, allowed uses, retention, and deletion constraints.

Use HF `datasets` for an approved local snapshot, `transformers` for models, and `peft`
for optional LoRA. Never enable remote dataset code without review. Do not upload workplace
text, labels, embeddings, adapters, or identity maps to a public Hub or hosted inference
service. Inspect schema and duplicate/group structure before choosing a sample.

## 6. Workshop curriculum: six hands-on labs

Preparation is additional: admit sources, select model revisions and licenses, create
fictional scenarios, draft and pilot the rubric, and prepare hidden test cases. The
permissive core can be completed as personal self-study.
Required skills are basic Python, train/validation/test evaluation, and introductory
statistics. A psychologist or psychometrician should co-design any extension claiming
psychological measurement validity.

| Lab | Hands-on work | Artifact and exit criterion |
|---|---|---|
| 1. What can language tell us? (3h) | Contrast traits, states, behavior, and role; critique [S6-S7]; audit HF dataset cards and licensing | Construct-to-evidence map and dataset admission register; every label has a defined unit and provenance |
| 2. Annotate before modeling (3h) | Label original fictional dialogues; mark spans, opportunity, and counterevidence. Self-annotation is sufficient for learning; use two independent annotators for a research agreement study | Pilot rubric and revised instructions; report disagreements only when independently measured, and never call self-annotation a reliability study |
| 3. Establish honest baselines (3h) | Train TF-IDF + linear models for a public task; compare frozen embeddings and a fixed-prompt local model | Group-aware split manifest and baseline report; no source conversation or duplicate crosses a custom split |
| 4. Evidence-grounded adaptation (3h) | Compare a generalist with one or two task LoRAs on the same permitted data; validate span references and abstention | Adapter ablation, schema checks, evidence-support audit; no synthetic style label counted as human ground truth |
| 5. Sufficiency and domain shift (3h) | Vary context and text budget; withhold topics; stress-test quote attribution, missing context, boilerplate, and fictional role swaps | Learning/coverage curves and error analysis; show where the system should refuse a trait inference |
| 6. Leadership mapping and preregistration (3h) | Apply provisional six-style rubric to fictional episodes; compare direct and behavior-mediated mapping; design independent workplace validation | Demo evidence report, research preregistration outline, and go/no-go decision; clearly separate demonstration from evidence about real people |

Without optional data clearance, Lab 4 can adapt an emotion classifier on GoEmotions
and a teaching-only empathy-expression classifier on original fictional dialogues with
human annotations. Report the latter as a mechanics demonstration, not real-world empathy
validation. EmpatheticDialogues, AnnoMI, EPITOME, and TalkLife are not prerequisites.

### Repository alignment and compute

Reuse patterns, not unvalidated personality claims, from:

- [Email Multi-LoRA](../email-multilora/README.md): small-model adapter training and paired
  evaluation. Its fictional persona replies are not a psychometric benchmark.
- [PersonaDesk proposal](../personal-agent-multilora/PROPOSAL.md): local-first, read-only
  workflows and human review. No automatic mailbox ingestion or real-person profiles.
- [SLM task-model plan](../slm-task-models/PLAN.md): narrow-task baselines and sealed gates.
- [Agent evaluation workshop](../agent-evals-vally/README.md): negative controls and
  independent graders; the agent never grades itself.

**CPU tier:** annotation, TF-IDF, compact embeddings, statistics, and report checks.
**GPU tier:** start with the repository's Qwen2.5-0.5B training pattern; a 10 GB GPU is a
planning target for short sequences and small batches, not a verified requirement for
this new workshop. Measure memory and runtime before committing to a configuration.
Larger-model comparisons and multi-adapter serving are optional, not evidence of validity.

The initialization supplies three notebooks, fictional fixtures, configurable model
profiles, baseline/training/evaluation code, tests, and a partial Workshop Hub entry.
The full six-lab research curriculum, independently annotated benchmark, evidence-report
schema, validated model card, and preregistration remain future artifacts. Initialization
outputs must not be presented as evidence that these later phases are complete.

## 7. Proposed AI architecture

```text
Approved public snapshot OR separately consented workplace export
  -> local minimization, redaction, authorship and consent checks
  -> thread reconstruction and speaker attribution
  -> grouping / deduplication / sealed splits
  -> opportunity and context assessment
  -> behavioral evidence extraction with exact source-span references
  -> per-construct predictors and calibrated abstention
  -> provisional, separately evaluated six-style mapping
  -> local evidence report for participant/researcher review
```

Start simple: TF-IDF with linear heads, then frozen embeddings with regularized heads,
then a fixed-prompt local instruction model. Add a generalist LoRA and task-specific
adapters only if held-out data justify the extra complexity. Train adapters by **task**,
not by employee. Compare models on identical data, context budgets, and group splits.

A behavior-mediated mapper accepts the evidence vector and available context. A direct
mapper sees the same permitted episode text. An ablation removes context; another removes
the behavior layer. Their relative performance tests the usefulness of decomposition,
not a causal theory of the brain.

### Output contract

Each proposed report must include:

- Scoped episode/window ID, intended use, and authorship/consent status.
- Observed constructs, ordinal scores or `not_observable`, and source-span references.
- Counterevidence, omitted context, observation opportunities, and alternative explanations.
- Dataset/model/rubric revisions, validation population, and distribution-shift warnings.
- Calibrated scores only where calibration exists; otherwise `uncalibrated`, not an
  invented confidence percentage. Model-generated verbal confidence is not calibration.
- Independent style-evidence scores, or an abstention reason. Avoid forcing one bucket.
- For any approved person-level estimate: number of independent episodes, observation
  duration, uncertainty interval, missingness, and a statement limiting interpretation.

Exact evidence text remains inside the authorized local review boundary. Published
reports use aggregate statistics and approved synthetic examples, not searchable quotes.
Schema validity and exact span matching are necessary but do not prove semantic support.
Humans audit whether each span actually supports the stated observation.

## 8. Paper-oriented study design

### Preregistered questions

- **RQ1:** Can models identify expressed empathy and decision-process behavior in unseen
  workplace episodes better than strong non-LLM baselines?
- **RQ2:** Do text-only person-level estimates predict independently collected criteria
  beyond role, topic, channel, and activity?
- **RQ3:** How do performance, uncertainty, and abstention change with text amount,
  independent episode count, and contextual diversity?
- **RQ4:** Does behavioral decomposition improve six-style prediction and evidence support
  compared with direct labeling?
- **RQ5:** Which effects fail to transfer across time, teams, channels, or populations?

**Primary pilot endpoint:** macro-F1 for a preregistered set of observable behavior labels
on held-out participants' workplace episodes. The label set and treatment of
`not_observable` must be frozen before evaluation.
Person-level psychometric associations and six-style prediction are distinct secondary
endpoints; success on the primary endpoint must not be reported as success on either.

### Cohort and independent criteria

1. Obtain institutional ethics review where applicable, privacy/legal review, and freely
   given consent with no employment consequences. Recruit through a process independent
   of line management. Include affected correspondents or exclude their content.
2. Use **30-50 volunteers only as a feasibility target**, over roughly 4-6 weeks. This
   is not a powered confirmatory sample and cannot support many subgroup comparisons.
3. Before a confirmatory study, simulate power at the participant/team level using pilot
   reliability, clustering, attrition, smallest meaningful effect, and multiplicity.
   Preregister the resulting sample size; thousands of messages are not thousands of
   independent participants.
4. Separately collect a named IPIP measure, permission-cleared decision-style measure,
   structured decision/support tasks, and independent observer assessments. Self-report
   and observer ratings are imperfect criteria; model their disagreement explicitly.
5. Define leadership criteria in two tiers: blinded episode ratings establish agreement
   with the rubric; separately observed tasks/appropriately consented multi-rater
   assessments test broader validity. Two raters reading the same emails are not an
   independent demonstration of stable leadership traits.

At inference, the **strict text-only condition** receives only authorized authored text,
speaker boundaries, and necessary conversational context. No questionnaire responses,
HR outcomes, demographic attributes, job-title fields, or hidden assessment labels.
Explicit self-descriptions, signatures, questionnaire quotations, forwarded material,
and third-party descriptions are removed or isolated in prespecified leakage analyses.

A separate context-assisted condition can receive consented role/channel/time metadata.
Do not call that condition "text alone." Criterion data remain in a separate access
boundary and are never included in prompts, retrieval indexes, or adapter training inputs.

### Split and leakage controls

- Hold out entire participants; keep all derived samples and time windows for a person
  together. Also prevent shared threads and near-duplicates from crossing partitions.
- For multi-person threads, split connected participant/thread groups, or exclude
  cross-partition threads. If one connected component dominates, recruit independent
  teams rather than quietly reverting to random-message splits.
- Preserve official public-dataset benchmarks as their own evaluation; label any custom
  speaker/thread-grouped split separately. If speaker identity is unavailable, state that
  person-level generalization cannot be tested with that dataset.
- Use nested grouped validation for model selection and a locked participant-held-out
  test for the final estimate. A future-window test on known participants is a separate
  temporal-stability experiment, not evidence of unseen-person generalization.
- Deduplicate quoted chains, templates, and transformed copies. Label or exclude
  AI-assisted/ghostwritten messages; evaluate the effect separately.
- Never infer traits of correspondents whose words appear only as quoted context.
- Public model pretraining contamination may be unknowable. Report this limitation and
  prioritize a prospective held-out cohort collected after model selection.

### Baselines and falsification tests

Include majority/mean predictors, text length/activity baselines, TF-IDF, frozen embeddings,
a fixed-prompt local LLM, and trained generalist/specialist variants. Role/context-only
baselines belong to the separate context-assisted analysis.

Run label permutation at the participant/group level, topic-held-out tests, temporal
holdout, shuffled-context controls, quoted-speaker attribution traps, and evidence-removal
tests. Use fictional counterfactual name/title swaps for stereotype sensitivity; these
do not establish real-world fairness. Compare decisions under the same valid observation
opportunities, not just the same number of messages.

### Evidence sufficiency experiment

Evaluate nested authored-token budgets such as 250, 1,000, 4,000, and 16,000 tokens, using
multiple prespecified sampling seeds and recording independent episodes, channels,
observation duration, truncation, and missingness. Keep each participant in the same split.
Run within-person budget comparisons on the subset eligible for all compared budgets;
report selection differences and coverage for the full cohort separately.

More text is not necessarily more independent information. A long quoted thread or many
templated acknowledgments may add little. Do not invent a universal minimum email count.
Declare a budget sufficient only for a stated endpoint and population when preregistered
accuracy, uncertainty, coverage, and stability criteria are met.

## 9. Evaluation and decision gates

The numerical gates below are **proposed research planning thresholds**, not empirical
results, clinical standards, or permission to deploy. Finalize them with the psychologist
before looking at the sealed test; document changes before data collection.

| Stage | Measurement | Proposed decision rule |
|---|---|---|
| Data admission | Rights, consent, provenance, labels, withdrawal procedure | All applicable approvals present; otherwise exclude the source |
| Annotation | Ordinal Krippendorff alpha per construct, with uncertainty; nominal agreement for opportunity/missingness | Target alpha >= 0.80; 0.67-0.80 supports exploratory analysis only; below 0.67, revise the construct/rubric before a confirmatory claim |
| Episode prediction | Macro-F1, per-label precision/recall, ordinal error, confusion with `not_observable` | Target >= 0.05 absolute macro-F1 improvement over the strongest prespecified baseline, with paired group-bootstrap 95% CI for the improvement above zero |
| Evidence support | Human-audited support precision and attribution correctness | Target >= 0.90 support precision; report CI and sample size. Fabricated spans and cross-person attribution are release-blocking defects |
| Uncertainty | Brier score, reliability diagrams, risk-coverage curves | On validation, select an abstention threshold targeting <= 10% error on accepted categorical predictions at >= 50% coverage; report test error, coverage, and CIs without retuning. This does not certify continuous trait scores |
| Person-level validity | Pearson/Spearman correlation, MAE, calibration, incremental out-of-sample R-squared | Positive incremental predictive value with uncertainty; preregister smallest meaningful effects and multiplicity correction. A significant correlation alone is insufficient |
| Leadership mapping | Per-style performance, macro metrics, calibration, unknown/mixed-case handling | Evaluate independently of behavior-task results; no six-style validity claim if its own criteria or ground truth fail |
| Robustness | Cross-team/channel/time transfer, counterfactual tests, approved subgroup analyses | Report failures and CIs; insufficient subgroup sample size means fairness is unresolved, not established |

Resample at the highest independent sampling unit supported by the design (for example,
team, then participant), not at the message row. Use paired resampling for model comparisons.
Preregister multiplicity handling for trait/style tests and report effect sizes with
uncertainty, including null and negative estimates.

Train calibrators on validation data only. Abstention may improve accepted-case accuracy
by excluding difficult people or contexts; always report coverage and who/what is excluded.
Do not generalize a workshop gate to hiring, performance assessment, or clinical use.

## 10. Privacy, participant safety, and allowed uses

**Default aim:** personal, noncommercial learning with permissive data and fictional
fixtures. Optional approved research may study participant-controlled communication.
**Excluded:** hiring, promotion, dismissal, employee ranking, covert monitoring,
manipulation, clinical diagnosis, and automated management decisions.

- Use local inference by default. Workplace data must not enter third-party prompts,
  hosted experiment trackers, ordinary agent memory, or public repositories.
- Consent must address individual messages, correspondents, retention, derived scores,
  model training, withdrawal, and the risk that employers could misuse an inference.
  Manager authorization is not a substitute for individual consent.
- Use pseudonymous IDs; keep reidentification keys separately encrypted with restricted
  access. Redaction reduces risk but does not make distinctive text anonymous.
- Exclude health, legal, intimate, and other highly sensitive content unless separately
  justified and approved. Do not infer mental health, protected traits, or neurological
  conditions. Optional sensitive public corpora need a facilitator content warning.
- Collect demographic attributes only with separate justification and consent for a
  sufficiently powered fairness analysis; never infer them from text to fill gaps.
- Treat messages as untrusted data: embedded instructions must not control tools, access,
  model routing, consent, or grading.
- Keep identity maps, raw text, evidence excerpts, embeddings, labels, and checkpoints
  outside version control and public artifacts. Before implementation, add narrowly
  scoped ignore rules and artifact checks; this proposal creates no data directories.
- Prefer no workplace fine-tuning in the pilot. If later permitted, participant deletion
  must account for learned artifacts: retire and retrain affected checkpoints rather
  than promise that deleting a row reliably removes its influence.
- Set an approved retention schedule before ingestion: a planning option is to delete
  raw donations within 90 days of verified processing and retain minimized research
  derivatives only for the approved study term. Backups and logs must follow the same
  policy; no schedule is activated by this document.
- Give participants review/correction and withdrawal procedures; explain when genuinely
  anonymized published aggregates can no longer be traced back for removal.
- Do not release private individual scores to employers. Publish aggregate findings,
  code, rubric, and explicitly synthetic test cases only after review.

Public psychological datasets are research materials, not a license to reproduce intimate
statements in a slide deck. Use source references and permitted paraphrases where possible.

## 11. Delivery plan and publication decision

| Phase | Planning duration | Deliverable / stop condition |
|---|---|---|
| Scope and source review | 1-2 weeks | Confirm six buckets; admit datasets; select independent criteria and permitted use |
| Facilitator preparation | 2-3 weeks | Pilot rubric, baselines, fictional fixtures, pinned environments, frozen evaluation plan |
| Workshop delivery | 18 contact hours | Six labs and evidence report; no claims about real employees |
| Approved research pilot | 12-16 weeks after approvals/recruitment | Feasibility cohort, independent criteria, leakage audit, sufficiency curves, bounded validity report |
| Confirmatory extension | Determined by power and recruitment | Independent cohort/organization, preregistered analysis, and manuscript |

Minimum roles: an ML/NLP lead, an organizational psychologist or psychometrician,
an annotation lead with trained raters, and a privacy/ethics reviewer. Neuroscience
expertise should shape the measurement assumptions, not lend unsupported biological
authority to a text classifier.

Compute cost is likely secondary to annotation, permissions, and participant recruitment.
Budget those explicitly; measure local model throughput before quoting training cost.
No performance, acceptance, or publication outcome is guaranteed.

### Candidate paper

**Working title:** *When Is Workplace Language Enough? Evidence Sufficiency and
Construct Validity for Communication-Based Leadership-Style Inference.*

The manuscript should separate:

1. Dataset and consent protocol.
2. Construct/rubric reliability.
3. Public-to-workplace transfer and behavioral baselines.
4. Independent person-level criterion validation.
5. Evidence sufficiency and selective prediction.
6. Six-style mapping and failure modes.
7. Bias, privacy, limitations, and prohibited uses.

**Go:** independently supported effects survive confound baselines and held-out testing,
with calibrated uncertainty and an ethical, reproducible protocol.
**Narrow:** behavior recognition works but person-level or six-style validity does not;
publish the narrower result without relabeling it "leadership assessment."
**No-go:** criteria are unreliable, rights/consent cannot be established, leakage drives
performance, or uncertainty remains incompatible with the proposed claim.

A well-controlled negative finding that operational text is insufficient can be a
valuable research result. A polished six-bucket dashboard without independent validation
is not.

## 12. Sources and verification record

Sources checked on 2026-11-09. "Confirmed" below refers to what the source states, not
proof that its findings generalize. Dataset licenses remain subject to admission review.
No full copyrighted paper is reproduced in this proposal.

| ID | Source | Evidence status and use |
|---|---|---|
| S1 | [GoEmotions HF card](https://huggingface.co/datasets/google-research-datasets/go_emotions/blob/main/README.md); [Demszky et al., 2020](https://arxiv.org/abs/2005.00547) | Confirmed from card: emotion taxonomy, simplified counts, Apache-2.0 declaration, raw identifiers |
| S2 | [EmpatheticDialogues HF card](https://huggingface.co/datasets/facebook/empathetic_dialogues/blob/main/README.md); [Rashkin et al., 2019](https://arxiv.org/abs/1811.00207) | Confirmed from card: conversational fields, utterance-row counts, CC BY-NC 4.0 |
| S3 | [Sharma et al. original repository](https://github.com/behavioral-data/Empathy-Mental-Health); [2020 paper](https://arxiv.org/abs/2009.08441) | Confirmed from repository: three empathy mechanisms, rationales, separate Reddit/TalkLife access; reuse permission not established by this review |
| S4 | [AnnoMI original repository](https://github.com/uccollab/AnnoMI); [HF conversion card](https://huggingface.co/datasets/to-be/annomi-motivational-interviewing-therapy-conversations/blob/main/README.md); [Wu et al., 2023](https://doi.org/10.3390/fi15030110) | Confirmed from repository/card: 133 demonstrations, original behavior annotations, reformatted HF conversations; original/mirror licensing reconciliation unresolved |
| S5 | [PANDORA, Gjurkovic et al., 2021](https://aclanthology.org/2021.socialnlp-1.12/) | Confirmed from abstract: partially labeled Reddit-user dataset and Big Five subset; availability/terms not cleared |
| S6 | [Peters and Matz, 2024, Large language models can infer psychological dispositions of social media users](https://pmc.ncbi.nlm.nih.gov/articles/PMC11211928/) | Confirmed from paper abstract: mean correlation 0.29 and heterogeneous demographic accuracy; not workplace or leadership validation |
| S7 | [Peters, Cerf, and Matz, 2024, Large Language Models Can Infer Personality from Free-Form User Interactions](https://arxiv.org/abs/2405.13052v1) | Confirmed from versioned preprint abstract: condition-specific correlations; cited as preprint evidence, not a workshop result |
| S8 | [International Personality Item Pool](https://ipip.ori.org/) | Confirmed from official site: items/scales are public domain; choice, scoring, reliability, and interpretation still require expertise |
| S9 | [Goleman, 2000, Leadership That Gets Results](https://hbr.org/2000/03/leadership-that-gets-results) | Original publication and situational-flexibility framing verified from publisher page; six-style taxonomy is a provisional framework, not a neuroscience-derived instrument |
| S10 | [Singer and Klimecki, 2014, Empathy and compassion](https://doi.org/10.1016/j.cub.2014.06.054) | Bibliographic record verified through indexed PubMed metadata; theoretical background, not evidence that text reveals neural states |
| S11 | [Ratcliff and McKoon, 2008, The diffusion decision model](https://doi.org/10.1162/neco.2008.12-06-420) | Indexed abstract verifies use of accuracy and response-time distributions in two-choice tasks; motivates limits on email-latency interpretation |
| S12 | [Scott and Bruce, 1995, Decision-Making Style: The Development and Assessment of a New Measure](https://doi.org/10.1177/0013164495055005017) | Bibliographic metadata verified; full instrument permissions/scoring not reviewed. Rational, intuitive, dependent, avoidant, and spontaneous styles are candidate research constructs, not labels supplied by the HF datasets |

**Next decision:** approve a public-data-only workshop preparation sprint, confirm the
six-bucket taxonomy, and recruit a psychometric co-designer. Do not start workplace
collection or person-level deployment on the strength of this proposal alone.
