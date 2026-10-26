# Multi-LoRA Leadership and Data Science Grilling Guide

Use this with the [five-slide presentation](multi-lora-final-results.pptx) and
[detailed companion](multi-lora-final-results-companion.md).

**Evidence cutoff:** 2026-10-20. The most defensible headline is:

> We proved that we can reproducibly train and verify multiple local LoRA adapters on one
> workstation. Classification validation is complete and encouraging. Persona-response
> evaluation is still preliminary, so we are asking for permission to run the rigorous
> validation phase—not permission to deploy autonomous email sending.

The answers below intentionally distinguish **what we measured**, **what we infer**, and
**what remains unproven**.

---

## Opening and executive questions

### Q1. What did you actually build?

**Answer:** We built two related but separate experimental systems:

1. A ten-label, multi-label email classifier with a generalist adapter, three domain
   specialists, and a router.
2. Ten independently trained persona-conditioned email-reply adapters using one pinned
   Qwen2.5-3B base architecture.

We also built data-lineage checks, checkpoint manifests, paired evaluation artifacts,
notebooks, and a staged evaluation plan. We did **not** build an autonomous email-sending
product or complete a production serving deployment.

### Q2. What is the one-sentence result?

**Answer:** LoRA training was operationally feasible on one RTX 3090, classification adapters
substantially improved validation performance, and persona adapters improved lexical overlap
on a small paired diagnostic—but persona quality, safety, and final-test performance are not
yet established.

### Q3. Why should leadership care?

**Answer:** If rigorous evaluation confirms the preliminary signal, one shared base plus small
role-specific adapters could offer more controllable behavior and lower storage duplication
than maintaining a fully fine-tuned model per role. The current work reduces technical
uncertainty; it has not yet demonstrated business ROI, production reliability, or risk
reduction.

### Q4. What decision are you asking leadership to make?

**Answer:** Approve the next evaluation phase: full paired validation, blinded human review,
robustness and grounding tests, ablations, and controlled serving benchmarks. I am **not**
asking for production approval based on eight-email persona diagnostics.

### Q5. Are you saying this is ready to deploy?

**Answer:** No. Classification has solid validation evidence, but still lacks untouched
test-set reporting and production monitoring. Persona reply generation lacks full validation,
human review, robustness testing, final-test evaluation, and serving isolation benchmarks.
Any current use should be limited to reviewed drafts in a controlled experiment.

### Q6. What is genuinely novel here?

**Answer:** LoRA itself is not novel. The contribution is an end-to-end, locally reproducible
workshop that connects data cleanup, multi-label routing, ten complete persona datasets,
independent adapter training, artifact verification, and an honest staged evaluation protocol.
It is an engineering and experimental integration, not a claim of a new learning algorithm.

### Q7. What did you prove, and what did you only demonstrate?

**Answer:** We proved that the pinned local pipeline can train, save, checksum, reload, and
compare these adapters on the available hardware. We measured classification validation
metrics on 312 emails. We demonstrated a preliminary persona lexical signal on eight emails.
We did not prove production quality, persona authenticity, safety, scalability, cost savings,
or superiority over all prompting and fine-tuning alternatives.

---

## Motivation and architecture

### Q8. Why use LoRA instead of prompt engineering?

**Answer:** Prompting is the required baseline, not something we are replacing without a test.
Our persona comparison disables LoRA while retaining the same persona prompt, so the observed
diagnostic delta isolates the adapter's effect under that prompt. However, we have not yet
run a broader prompt-optimization study. The next phase should compare a well-engineered
prompt-only baseline, a generic reply adapter, and the persona-specific adapters.

### Q9. Why not just use one generalist model?

**Answer:** We should if it performs as well. In classification, the single generalist had the
highest micro-F1 for both tested base models. That is evidence **against** assuming specialists
are automatically better. Persona specialization remains a separate hypothesis: adapters may
help stable role-specific voice and boundaries, but that requires human and robustness
evaluation before we prefer it over one general reply model.

### Q10. If the classification generalist won, doesn't that undermine the Multi-LoRA story?

**Answer:** It undermines the simplistic claim that more specialists always improve aggregate
quality, and the presentation says so. The experiment is useful precisely because it exposes
that tradeoff. Specialists may still be justified by governance, isolation, independent
release cycles, or minority-domain behavior, but aggregate micro-F1 alone did not justify
them in this classification setup.

### Q11. Why are classification and reply generation in the same presentation?

**Answer:** Classification established the reusable local training, routing, artifact, and
evaluation machinery. Reply generation extends the workshop to persona-conditioned behavior.
They are part of one learning journey, but their scores are not directly comparable. I will
not use classification success as evidence that reply quality is solved.

### Q12. What exactly is a LoRA adapter?

**Answer:** It is a small set of learned low-rank weight updates injected into selected layers
of a frozen pretrained model. It is not a standalone model. It must be loaded with the exact
compatible base architecture, tokenizer, model revision, target modules, and prompt contract.

### Q12a. What is the original rank of Qwen2.5-3B-Instruct, and are we reducing it to eight?

**Answer:** The model does not have one original matrix rank. Each weight matrix has its own
dimensions and rank. "3B" describes approximately three billion parameters, not rank. For the
projections targeted by our persona adapters:

| Weight matrix | Original shape (output x input) | Maximum possible rank | LoRA update rank |
|---|---|---|---|
| `q_proj` | 2,048 x 2,048 | 2,048 | At most 8 |
| `v_proj` | 256 x 2,048 | 256 | At most 8 |

These shapes follow PyTorch's weight convention and the
[official Qwen model configuration](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/config.json):
hidden size 2,048, 16 query heads, and two key/value heads. Each head has 128 dimensions, so
the value projection outputs 2 x 128 = 256 features. The dimensions give maximum possible
ranks; we have not measured the actual numerical ranks of the pretrained weights.

LoRA freezes the original weight matrix `W` and trains a correction `BA`, giving
`W_effective = W + BA`. With rank 8, `A` has shape `8 x input` and `B` has shape
`output x 8`, so `rank(BA) <= 8`. The combined weight is not restricted to rank eight.

**Say it simply:** "We are not shrinking the base model to rank eight. We keep its original
weights and learn a rank-eight correction to each selected query and value projection."

### Q13. Did you merge adapters into the base model?

**Answer:** No. They remain separate PEFT adapter artifacts. That preserves provenance and
allows the base to be reused. The local persona backend loaded one selected adapter at a time.
We generated a static vLLM registration command, but did not claim a completed shared-serving
benchmark.

### Q14. How is the correct persona selected?

**Answer:** The experiment uses an explicit trusted client ID mapped through a registry to a
profile, dataset, and adapter name. We should not infer an employee identity from arbitrary
email text. A production system would require authenticated tenant/user context and
authorization before selecting an adapter.

### Q15. Could the wrong customer receive the wrong adapter?

**Answer:** That is a serious multi-tenant risk. The current registry and manifest checks
protect local identity and lineage, but they are not a production authorization layer.
Serving must test adapter isolation, authenticated selection, request logging without content
leakage, cache behavior, and fail-closed handling before any multi-tenant use.

---

## Data preparation and validity

### Q16. What data did you use?

**Answer:** The source was the pinned `imnim/multiclass-email-classification` dataset. It had
2,105 raw records. We quarantined two identical-text records with conflicting labels, retained
2,103 unique records, and used stable 1,473/312/318 train/validation/test partitions.

### Q17. The dataset says “multiclass.” Why do you call it multi-label?

**Answer:** The actual schema contains a list of labels, and one email can belong to multiple
categories. Treating it as mutually exclusive multiclass data would discard valid supervision
and make specialist routing misleading. The implementation preserves the label array.

### Q18. How did you prevent leakage?

**Answer:** We normalized exact text, quarantined the conflicting duplicate group, generated
stable IDs, and ensured no normalized exact ID crossed splits. This addresses exact-duplicate
leakage. It does **not** prove that near-duplicates, related threads, paraphrases, or semantic
clusters do not cross partitions. That is a remaining audit.

### Q19. You say you have 21,030 persona rows. Do you really have that many independent examples?

**Answer:** No. We have 2,103 unique incoming emails crossed with ten named personas, yielding
21,030 persona-email rows. The unit of independent source-email variation remains 2,103.
Treating all persona-email rows as independent would overstate statistical precision.

### Q20. Who wrote the “ground-truth” replies?

**Answer:** The current chat assistant and background assistants authored the synthetic
reference replies from each email and persona profile. Deterministic scripts assembled and
validated the files; keyword templates did not author the prose. These are workshop references,
not independently adjudicated human truth.

### Q21. Isn't training and evaluating against AI-authored replies circular?

**Answer:** It is a real limitation. Lexical metrics may reward imitation of the authoring
model's wording and style. That is why the references are supervision and diagnostics, not
proof of human preference. The next phase needs blinded human review, multiple acceptable
answer criteria, grounding checks, and ideally a human-authored or independently reviewed
subset.

### Q22. Did real clients approve these personalities?

**Answer:** No. The personas are synthetic workshop specifications. We should not describe
them as measured traits of real employees or customers. A real deployment would require
consent, role governance, profile ownership, change control, and an opt-out mechanism.

### Q23. Is the dataset representative of our production email?

**Answer:** We have not established that. It is a public workshop dataset with ten broad
labels. Its topic mix, writing style, language distribution, thread length, confidentiality,
and operational risk may differ from production. External validity requires a governed,
de-identified, representative evaluation set from the target domain.

### Q24. Could the base model have already seen this public dataset?

**Answer:** That cannot be ruled out from the available evidence. Pinned splits prevent
leakage within our fine-tuning pipeline, but not possible pretraining contamination of a
public dataset. We should describe results as task adaptation on this benchmark, not as proof
of generalization to unseen real-world distributions.

### Q25. Is the test set really sealed if reference replies already exist?

**Answer:** The test inputs and references exist because the complete response datasets were
authored before training. “Sealed” means we have not used test-model generations or test
metrics to select checkpoints, prompts, thresholds, or claims. Anyone inspecting test
references during development could still introduce human leakage, so access and decision
logs should be tightened before final evaluation.

### Q26. What about data licensing and privacy?

**Answer:** The source publisher declares MIT for the dataset; model licenses are separate
and must be reviewed independently. The workshop uses public/synthetic material, not private
mail. A production path needs legal review for source rights, model terms, retention, user
consent, sensitive-data handling, regional requirements, and whether generated drafts become
business records.

---

## Training design

### Q27. Why Qwen2.5-3B for persona replies?

**Answer:** It was a practical local choice that fit the RTX 3090 and supported the required
chat/PEFT workflow. It was not selected as the winner of a controlled model bake-off. A fair
next experiment should compare it with strong prompt-only and alternative-model baselines
under the same data, decoding, and evaluation contract.

### Q28. Why not train the persona adapters on Nemotron?

**Answer:** We successfully trained an 8B Nemotron model for the earlier classification task,
so local NVIDIA-model training is not categorically impossible. We chose Qwen 3B for the
ten-adapter reply run because it was lighter and suitable for sequential local iteration.
The newly available `nemotron-local` server is a different 4B base and can be evaluated as a
remote baseline, but it cannot load our Qwen adapters.

### Q29. Why rank 8 and only `q_proj`/`v_proj`?

**Answer:** They are common, memory-efficient LoRA settings and worked within the hardware
budget. They were not established as optimal. A controlled ablation should compare rank,
target modules, and possibly LoRA alpha/dropout while limiting multiple-comparison bias.

### Q30. Why one epoch for persona training?

**Answer:** It was a bounded first full run across ten clients. Each adapter completed one
pass and checkpoint evaluation on all 312 validation rows. One epoch limits cost and
overfitting risk, but it may underfit. Learning curves and a predeclared small sweep are
needed before claiming the selected schedule is optimal.

### Q31. Why not use QLoRA or full fine-tuning?

**Answer:** The 3B base fit BF16 LoRA on the 24 GiB GPU, so quantization was not necessary
for this feasibility run. Full fine-tuning would increase memory, storage, and operational
cost. We have not benchmarked whether QLoRA, full fine-tuning, or another PEFT method would
produce better quality per dollar.

### Q32. Were adapters trained independently?

**Answer:** Yes. Every client started from the same pinned frozen base with a fresh LoRA
adapter and optimizer. Adapters were trained sequentially for hardware efficiency, not
stacked on top of one another.

### Q33. What loss did you optimize?

**Answer:** Completion-only causal-language-model loss. Prompt and padding tokens were masked,
so optimization focused on the reference reply and end-of-sequence token. Lower loss means
better reference-token prediction under that contract; it does not directly measure persona
authenticity, grounding, helpfulness, or safety.

### Q34. Can we compare loss across personas?

**Answer:** Not as a simple quality ranking. Personas have different response lengths,
vocabularies, and conditional distributions. Training and validation losses are useful within
a client for checkpoint diagnostics, but lower loss for one persona does not prove that its
adapter is better than another's.

### Q35. How long and how expensive was training?

**Answer:** The sum of recorded adapter-training elapsed times was about 96.7 minutes on one
RTX 3090 for ten persona adapters. That excludes dataset authoring, preparation, downloads,
environment setup, classification experiments, evaluation generation, and engineering time.
We did not perform a complete total-cost-of-ownership study.

### Q36. How large are the adapters?

**Answer:** Each top-level Qwen 3B LoRA weight file is about 7.05 MiB. A complete client
directory is about 43.5 MiB because it also retains tokenizer assets and a Trainer checkpoint
with optimizer state. The shared base weights are separate and much larger.

### Q37. How reproducible is the run?

**Answer:** We pinned dataset and model revisions, seed, split IDs, prompt contract, target
modules, versions, and configuration. Manifests record hashes and lineage; checkpoints retain
Trainer state. That is strong run provenance, but exact floating-point reproduction can still
vary across hardware, kernels, drivers, and library behavior. We also have only one training
seed, so stability is not yet measured.

---

## Classification results

### Q38. What were the strongest classification results?

**Answer:** On 312 validation emails:

- Qwen 0.5B generalist: micro-F1 **0.8028**, macro-F1 **0.7252**, exact match **67.63%**.
- Nemotron 8B generalist: micro-F1 **0.8465**, macro-F1 **0.7967**, exact match **73.72%**.

Those are validation results, not final-test estimates.

### Q39. Why is Nemotron's unadapted base score so poor?

**Answer:** Under this experiment's strict JSON output contract, the Nemotron base had a
40.38% invalid-output rate and micro-F1 0.1340. That may reflect output-contract/prompt
alignment as much as semantic classification ability. We should not generalize this result
into “Nemotron is a bad base model.”

### Q40. Is the Nemotron-versus-Qwen comparison fair?

**Answer:** It is controlled on dataset, split IDs, seed, adapter definitions, routing, target
modules, and evaluation contract, but the models differ greatly in size, tokenizer, prompt
behavior, latency, and base-format compliance. It is an experiment under one contract, not a
complete model ranking or cost-normalized benchmark.

### Q41. Did specialists improve classification?

**Answer:** Not on the primary aggregate metric. For Qwen, generalist micro-F1 was 0.8028,
all-specialist was 0.8020, and routed was 0.8004. All-specialist did achieve the highest Qwen
macro-F1 at 0.7343. For Nemotron, the generalist was strongest on both micro- and macro-F1.

### Q42. Then what did routing accomplish?

**Answer:** It reduced specialist calls from exactly 3.000 to 1.032 calls per email—about
65.6%—while changing Qwen micro-F1 from 0.8020 to 0.8004 relative to all specialists. That is
a call-count result, not proof of an equal latency or cost reduction. The generalist still
made only one call and had slightly better micro-F1.

### Q43. Was the router evaluated fairly?

**Answer:** It used only subject/body at inference, never ground-truth labels. However, its
threshold was selected on validation, so validation routing metrics are development results.
The finance-domain validation recall was 0.84 even though aggregate domain recall met the
0.95 target; aggregate thresholds can hide minority-domain weakness.

### Q44. Why report both micro-F1 and macro-F1?

**Answer:** Micro-F1 pools all label decisions and is influenced by common labels. Macro-F1
gives each label equal weight and is more sensitive to minority labels. The fact that they
select different Qwen strategies is a warning against choosing one headline metric without
business-weighted error costs.

### Q45. Why not report accuracy?

**Answer:** Plain single-label accuracy is inappropriate for a multi-label task. Exact match,
micro/macro F1, per-label precision/recall, Hamming loss, invalid-output rate, and calls per
email provide a more complete picture.

---

## Persona evaluation results

### Q46. What are the persona-response results?

**Answer:** On a saved paired diagnostic of eight validation emails per persona, the
equal-weight mean token F1 increased from 0.1916 to 0.3352 and ROUGE-L from 0.1430 to 0.2767.
All ten personas improved on both metrics. These are encouraging diagnostics, not a quality
certification.

### Q47. Is that 80 independent evaluation emails?

**Answer:** No. It is the same eight incoming email IDs evaluated for ten personas: 80
persona-email comparisons and 160 base/adapted outputs, but only eight independent source
emails. Any aggregate inference must cluster by incoming email.

### Q48. Why did you evaluate only eight emails?

**Answer:** The pipeline used eight as a bounded post-training smoke/diagnostic generation
limit across all ten clients. Full checkpoint validation loss used all 312 validation rows,
but full text generation and quality scoring did not. The correct next step is to generate
all 312 validation emails per persona before stronger claims.

### Q49. You say validation used 312 rows. Isn't that the same as full evaluation?

**Answer:** No. The Trainer computed validation cross-entropy loss over 312 reference replies
for checkpoint selection. The saved base/adapted generation comparison produced text for only
eight rows per client. Loss and generation-quality evaluation answer different questions.

### Q50. Why use token F1 and ROUGE-L for replies?

**Answer:** They provide deterministic lexical-overlap diagnostics against a reference. They
are useful for detecting a signal and obvious regressions, but one email can have many valid
replies. These metrics do not establish factual grounding, persona voice, helpfulness,
boundary adherence, or safety.

### Q51. Exact match was zero. Is that a failure?

**Answer:** Not necessarily. Exact string match is normally near zero for open-ended
generation because many phrasings can be valid. It is reported as a strict diagnostic, not
the primary measure. A copied reference could score perfectly and still be operationally
inappropriate in another context.

### Q52. Why did adapted replies appear faster?

**Answer:** The adapted outputs were also substantially shorter on average: mean
generated/reference length ratio moved from 1.9809 to 0.8482. Generation latency depends on
output tokens, so the observed sample latency difference is confounded by length. It is not
a controlled throughput or adapter-overhead benchmark.

### Q53. Are shorter adapted replies better?

**Answer:** Not automatically. They are closer to reference length on this sample, but they
could omit necessary information. Human reviewers must score relevance, completeness,
actionability, and grounding rather than treating brevity as quality.

### Q54. Did the adapters improve persona fidelity?

**Answer:** We do not yet have sufficient evidence to say so. Lexical overlap with
persona-specific references increased, which is consistent with better adaptation, but we
need blinded human ratings, profile-specific style diagnostics, wrong-adapter controls, and
cross-persona confusion analysis.

### Q55. Are the results statistically significant?

**Answer:** We did not compute a defensible population-level significance result from the
eight-email diagnostic. The sample is too small, the same emails repeat across personas, and
there is only one run seed. Full validation should use paired email-level differences and
clustered bootstrap confidence intervals.

### Q56. Why are there no confidence intervals on the slides?

**Answer:** Because adding a narrow-looking interval from eight reused emails would create
false precision. The slides explicitly label the result as preliminary. Confidence intervals
belong after the full paired validation with the correct resampling unit.

### Q57. Could the adapter just be memorizing training replies?

**Answer:** The diagnostic IDs are from the validation partition, not the training partition,
and exact match was zero, so there is no evidence of verbatim reference memorization in those
outputs. However, overlap metrics and exact-ID separation cannot rule out pattern memorization,
near-duplicate leakage, or stylistic imitation. We need nearest-neighbor and copy-rate audits.

---

## Evaluation design and next experiments

### Q58. What is the next scientifically credible experiment?

**Answer:** Generate base and adapted replies for all 312 validation emails for every persona
with identical prompts, decoding, runtime, and ordered IDs. Measure health, lexical and style
diagnostics, grounding flags, and slices. Then run randomized blinded human A/B review with
at least two reviewers and predeclared rubrics.

### Q59. What should the human rubric measure?

**Answer:** Persona voice, relevance, actionability, grounding, and boundary adherence on
anchored 1–5 scales, plus A/B/tie preference and evidence-based notes. Reviewers should be
blind to system identity; disagreements and adjudication should be recorded.

### Q60. What baselines are still missing?

**Answer:** At minimum:

- A carefully optimized prompt-only Qwen 3B baseline.
- One shared generic reply adapter.
- Correct-persona versus wrong-persona adapter.
- The generic authored-reference baseline where appropriate.
- An alternative base/model baseline, such as the available Nemotron 4B service.
- Optionally retrieval-augmented prompting if role knowledge—not style—is the real need.

### Q61. What would prove that ten adapters are better than one?

**Answer:** Persona-specific adapters should beat a shared reply adapter and prompt-only base
on blinded persona fidelity and overall preference without degrading grounding, relevance,
critical-error rate, latency, or operational isolation. The improvement should persist across
personas and source-email slices with uncertainty intervals.

### Q62. How will you avoid p-hacking?

**Answer:** Pre-register the primary metric, rubric, critical-error definitions, slice policy,
bootstrap method, and release thresholds before opening full results. Limit hyperparameter
search, keep the final test sealed, and report all planned comparisons rather than only wins.

### Q63. What is the correct statistical unit?

**Answer:** The incoming email is the primary unit. For an across-persona aggregate, bootstrap
incoming emails and keep all persona observations for a selected email together. Treating
80 persona-email rows from eight emails as 80 independent observations would underestimate
uncertainty.

### Q64. What robustness tests are required?

**Answer:** Long quoted threads, vague subjects, signatures/disclaimers, conflicting dates,
changed names/numbers/amounts, multilingual or code-switched mail, adversarial instructions
inside email content, sensitive information, and requests outside the persona's authority.
Every critical grounding or commitment failure should receive manual review.

### Q65. Would you use an LLM as judge?

**Answer:** Only as a supplemental measure. The judge must be independent from the trained
base, use a fixed rubric and strict output, run both A/B orders to measure position bias, and
be calibrated against a human-scored subset. It cannot replace human review for release.

### Q66. When will you touch the final test set?

**Answer:** After prompts, adapters, decoding, thresholds, rubric, and acceptance criteria are
frozen using validation. Then run the 318-email test once. If we change the system after
seeing test results, those results become development evidence and we need a new holdout.

### Q67. What are the success thresholds?

**Answer:** They have not yet been approved, and I should not invent them after seeing results.
Before full evaluation, product, risk, and data-science stakeholders should pre-register a
minimum human-preference margin, no-regression bounds for relevance/grounding, a maximum
critical-error rate, latency/cost constraints, and persona-level minimums.

---

## Safety, governance, and production

### Q68. What is the biggest safety risk?

**Answer:** A plausible but unsupported commitment—approval, payment, booking, cancellation,
legal position, deadline, or disclosure—written in an authoritative persona voice. Human
approval, grounding checks, role boundaries, and high-risk workflow restrictions are mandatory.

### Q69. Can prompt injection in an email override the persona instructions?

**Answer:** It could. Email content is untrusted data. The current prompt tells the model to
respect boundaries, but that is not sufficient security. We need adversarial tests, clear
instruction/data separation, output policy checks, least-privilege tools, and no autonomous
action based solely on generated text.

### Q70. Can we automatically send the generated emails?

**Answer:** Not from this evidence. The safe current posture is draft-only with human review.
Any future automation should be limited to narrowly defined low-risk cases after measured
false-action and grounding rates meet preapproved thresholds, with auditability and rollback.

### Q71. How do we handle PII and confidential email?

**Answer:** Do not send it to an unapproved endpoint. A production design needs data
classification, encryption, retention/deletion rules, access controls, tenant isolation,
redacted telemetry, regional processing, incident response, and approved model/provider
terms. The workshop's public/synthetic data does not validate those controls.

### Q72. How do we update a person's profile?

**Answer:** Treat the profile, dataset, and adapter as a versioned governed package. A change
creates a new lineage and evaluation cycle; it should not silently mutate a deployed identity.
The profile owner should approve changes, and rollback should retain the prior verified bundle.

### Q73. How do we monitor drift?

**Answer:** Monitor input distribution, language/thread length, route frequency, output
validity, abstention/review rates, grounding and policy flags, human edits, latency, and
persona-specific quality. Sample reviewed outputs under an approved privacy process and
trigger re-evaluation rather than automatically retraining on unvetted user edits.

### Q74. What would the serving architecture look like?

**Answer:** A trusted identity layer selects an authorized adapter; a shared compatible base
serves the request; prompts are built from versioned profiles; outputs pass validation and
risk checks; and drafts go to human review. Adapter registry, cache isolation, rate limits,
telemetry, and rollback are first-class components. We generated a vLLM registration command,
but did not benchmark this architecture live.

### Q75. Can we use the `mastersmac` Nemotron service?

**Answer:** Yes as a separate inference baseline. We verified an OpenAI-compatible
`/v1/chat/completions` request to `nemotron-local`, backed by
`nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16`. Setting
`chat_template_kwargs.enable_thinking=false` produced a clean reply. It does not advertise
our Qwen persona adapters, so it cannot replace evaluation of those adapters.

### Q76. Does this work in Azure Foundry or NVIDIA NIM?

**Answer:** Local PEFT success does not prove a managed service supports this exact model,
revision, adapter format, target modules, and dynamic loading controls. Managed deployment
must be verified against the specific model profile and platform contract. Do not present
the local artifacts as already deployed to Foundry or NIM.

### Q77. What is the production cost?

**Answer:** Unknown. We measured local recorded training time, not cloud GPU cost, serving
throughput, concurrency, utilization, engineering operations, review labor, or incident cost.
A production decision needs a controlled benchmark and total-cost model against prompt-only
API usage and simpler non-LLM alternatives.

### Q78. What is the rollback plan?

**Answer:** Version the base revision, adapter, tokenizer, profile, prompt, and policy together.
Retain the previously approved bundle; route back to it or to prompt-only/manual handling if
quality or safety monitoring fails. Never overwrite a deployed adapter in place.

---

## Evidence, auditability, and hostile closing questions

### Q79. Where is the evidence that training actually happened?

**Answer:** The local artifact tree contains:

- Overall pipeline result and status under `artifacts/persona-qwen2.5-3b-full/persona_pipeline/`.
- One manifest per client with configuration, elapsed time, loss history, versions, hashes,
  and best checkpoint.
- Checkpoint directories with adapter weights, optimizer, scheduler, RNG state, and
  `trainer_state.json`.
- Paired base/adapted generated predictions under `persona_evaluation/`.
- Separate full classification run reports and per-strategy metric JSON files.

The [artifact reuse guide](../../artifacts/README.md) explains the layout. Large artifacts are
Git-ignored, so a repository clone alone is not the evidence archive.

### Q80. How do we know the artifacts were not mixed between clients?

**Answer:** The registry maps client ID to profile, CSV, and adapter. Manifests record client
identity and data fingerprints. The verifier recomputes committed CSV/profile lineage and
hashes of required adapter/tokenizer files before inference. A mismatch fails explicitly.

### Q81. Why aren't the model weights in Git?

**Answer:** They are large binary run outputs and include checkpoints and prediction artifacts.
Git is not an appropriate model registry. The README is versioned; weights remain local and
ignored. A production path needs an access-controlled artifact registry with immutable
versioning, checksums, retention, and promotion stages.

### Q82. Did you cherry-pick the best-looking examples?

**Answer:** The diagnostic used the pipeline's ordered first eight validation IDs for every
persona and both modes, not manually selected per-persona wins. But eight ordered rows may
still be unrepresentative. That is why we are not presenting them as population estimates.

### Q83. Did you run multiple seeds?

**Answer:** No. The completed full runs use seed 2026. Reproducibility metadata is strong, but
training variance is unmeasured. At least a targeted multi-seed study for representative
personas and key baselines is needed before attributing small deltas to the method.

### Q84. Why should we trust results produced by the same team that built the system?

**Answer:** You should trust the traceable evidence, not the team by default. The artifacts,
hashes, fixed IDs, manifests, and explicit limitations make independent review possible.
The next phase should include blinded reviewers and, ideally, an evaluator who did not build
the training pipeline.

### Q85. What would make you stop the project?

**Answer:** Stop or redesign if persona adapters fail to beat a strong shared/prompt-only
baseline, increase critical grounding or boundary violations, require unacceptable human
review, cannot isolate tenants, do not meet latency/cost constraints, or depend on data we
cannot lawfully and ethically use.

### Q86. What is the strongest criticism of your current presentation?

**Answer:** The persona slide shows a consistent lexical improvement that can look more
conclusive than it is. It is based on only eight unique emails and synthetic references.
The slide mitigates this by labeling the result provisional, but the correct response is to
lead with that limitation before anyone else raises it.

### Q87. What is your strongest defense?

**Answer:** We did not hide negative or inconclusive findings. The generalist beat specialists
on classification micro-F1, the persona sample is explicitly small, and deployment is not
claimed. The pipeline and evidence are sufficiently mature to justify a rigorous next
experiment, which is the decision being requested.

### Q88. If you had one more slide, what would you add?

**Answer:** A “claims versus evidence” slide:

| Claim | Current status |
|---|---|
| Local adapter training works | Verified |
| Classification improves on validation | Verified |
| Ten persona adapters train and reload | Verified |
| Persona lexical overlap improves | Preliminary, eight emails |
| Humans prefer adapted replies | Unknown |
| Replies are grounded and safe | Unknown |
| Multi-adapter serving scales economically | Unknown |
| Production deployment is approved | No |

### Q89. What should you say if you do not know an answer?

**Answer:** “We have not measured that yet. The current evidence establishes **X**, not **Y**.
The experiment I would run is **Z**, and I would predefine the decision threshold before
seeing the result.” Do not fill an evidence gap with intuition.

### Q90. What should your final closing statement be?

**Answer:** “The value of this work is not that it proves personalized email is ready. It
turns a broad idea into a reproducible system with visible evidence and visible gaps. The
next investment should buy decision-quality evidence: full paired validation, blinded human
review, safety stress tests, and controlled serving economics.”

---

## Rapid-fire number check

### Q91. What numbers must you remember without looking?

**Answer:**

| Question | Number |
|---|---:|
| Raw / retained emails | 2,105 / 2,103 |
| Train / validation / test | 1,473 / 312 / 318 |
| Named persona adapters | 10 |
| Qwen persona base | Qwen2.5-3B-Instruct |
| Persona LoRA | Rank 8, `q_proj` + `v_proj`, 1 epoch |
| Recorded persona training time | 96.7 minutes total |
| Persona diagnostic source emails | 8 unique emails |
| Mean persona token F1, base to adapted | 0.1916 to 0.3352 |
| Mean persona ROUGE-L, base to adapted | 0.1430 to 0.2767 |
| Qwen classifier generalist micro-F1 | 0.8028 |
| Nemotron classifier generalist micro-F1 | 0.8465 |
| Specialist calls, all to routed | 3.000 to 1.032 |
| Full persona generation validation complete? | No |
| Persona final test complete? | No |
| Human preference study complete? | No |

### Q92. Which numbers should you never combine?

**Answer:** Do not compare classification micro-F1 with persona token F1 as if they share a
scale. Do not combine 312-row validation loss with eight-row generated-text metrics. Do not
call 80 persona-email comparisons 80 independent emails. Do not convert the 65.6% reduction
in model calls into a 65.6% cost or latency claim.

### Q93. What three phrases should you repeat during hard questioning?

**Answer:**

1. “That is validation evidence, not final-test evidence.”
2. “The persona result is a preliminary eight-email paired diagnostic.”
3. “The next step is a pre-registered human and robustness evaluation, not deployment.”