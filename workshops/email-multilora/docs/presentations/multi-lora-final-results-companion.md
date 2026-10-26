# Multi-LoRA for Email: Final Experiment Readout

Slide companion and speaker notes for [the five-slide presentation](multi-lora-final-results.pptx).

**Evidence cutoff:** 2026-10-20. "Final" describes this presentation of completed work, not a
completed final-test evaluation or production release.

## Executive summary

The experiment progressed from multi-label email classification to persona-conditioned email
reply generation. Classification established a local, reproducible LoRA training and routing
workflow. The final training stage produced ten independent Qwen2.5-3B persona adapters on one
RTX 3090.

Three findings should be presented separately:

1. **Classification validation is complete:** on 312 validation emails, Qwen 0.5B generalist
   micro-F1 was 0.8028 versus 0.4517 for its base; Nemotron Nano 8B generalist was 0.8465 versus
   0.1340 for its base under this experiment's strict JSON prompt/output contract.
2. **Persona training is complete, but generation evaluation is preliminary:** all ten adapters
   trained on 1,473 emails and used 312 validation examples for checkpoint evaluation. On the
   saved eight-email generation diagnostic, all ten improved mean token F1 and ROUGE-L.
3. **Quality certification is not complete:** the diagnostic covers only eight unique incoming
   emails reused across ten personas, not 80 independent emails. No full persona generation
   validation, blinded human study, final-test evaluation, or live serving benchmark is claimed.

The defensible conclusion is local feasibility plus encouraging validation/diagnostic evidence.
It is not that multi-adapter specialization always beats a generalist, or that the generated
replies are ready to send without review.

## Slide 1 - One base, many email behaviors

### Purpose

Explain the motivation before showing scores.

### Speaker notes

Email automation has at least two different problems. Classification assigns structured labels
to incoming messages. Reply writing generates useful, grounded text in a selected person's
communication style and role boundaries. A generic model can be prompted for either task, but
the experiment asks whether small trained adapters improve consistency without maintaining a
separate fully fine-tuned model for each behavior.

LoRA freezes the pretrained base and learns low-rank updates to selected projection matrices.
An adapter is not a complete language model and is usable only with its matching base,
tokenizer, prompt contract, and revision. Multiple adapters can share a compatible base at
inference, although the completed persona pipeline trained them sequentially and loaded one
client at a time for local PEFT generation.

Rank 8 describes the adapter update, not the rank of the base model. For Qwen2.5-3B-Instruct,
the targeted `q_proj` weights are 2,048 x 2,048 (maximum rank 2,048), and `v_proj` weights are
256 x 2,048 (maximum rank 256), using output-by-input shapes from the
[official model configuration](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/config.json).
Actual pretrained numerical ranks were not measured. LoRA uses `W_effective = W + BA`, where
`rank(BA) <= 8`; the combined weight is not restricted to rank eight. "3B" refers to parameter
count, not rank. See [the presenter Q&A](PRESENTER_GUIDE.md) for the detailed explanation.

The work followed two stages:

- **Stage A, classification:** generalist versus domain specialists, including routing.
- **Stage B, replies:** ten synthetic persona-specific adapters using a larger Qwen 3B base.

The primary reply question is: for the same email and persona prompt, does a trained adapter
improve useful, persona-consistent replies without increasing unsupported claims or cost?
Current lexical diagnostics answer only a narrow part of that question.

### Claims to avoid

- Do not equate a classification improvement with improved reply quality.
- Do not call workshop personas real client behavior learned from actual sent mail.
- Do not claim production multi-tenant serving, Foundry adapter hosting, or NVIDIA NIM support
  from successful local PEFT training.

## Slide 2 - Prepare the data before adapting the model

### Source and cleanup

| Item | Recorded value |
|---|---|
| Dataset | `imnim/multiclass-email-classification` |
| Source revision | `e95090f0bb6dae0b05c9cd6db314dcae1d40db3f` |
| Source file SHA-256 | `1093f1a3191e52b715ae728609b2e15bac71ba2573814a968856c43b009a0b30` |
| Raw records | 2,105 |
| Quarantined records | Two identical-text records with conflicting labels |
| Retained emails | 2,103 |
| Taxonomy | Ten labels; multiple labels may apply to one email |
| Split approach | Normalized exact deduplication, iterative multi-label split, seed 2026 |
| Train / validation / test | 1,473 / 312 / 318 |

The dataset name says "multiclass", but the actual labels form a multi-label array. Preserving
that structure is necessary for correct supervision and routing. Exact-ID separation prevents
normalized exact-duplicate leakage; it is not proof that near-duplicates, related threads, or
semantic overlaps have been eliminated.

### Constructing reply supervision

Each retained email was paired with a synthetic persona profile defining name, role, style,
and boundaries. The current chat assistant and background assistants authored the reply text
from the email and profile. Deterministic scripts assembled CSVs and checked schema, coverage,
IDs, split assignment, and hashes; scripts did not generate prose from keyword templates.
The recorded authoring process did not use external generation endpoints or a local LLM.

The durable response collection has 11 sets of 2,103 responses: ten named personas and one
generic baseline, totaling 23,133 rows. The completed persona training run used only the ten
named personas: **21,030 persona-email rows representing 2,103 unique source emails**.
These are reference responses authored for the workshop, not independently adjudicated human
ground truth. Structural validation should not be described as a full semantic or safety audit.

Each CSV retains the original email ID and train/validation/test partition. A JSON registry
maps client ID to profile file, response CSV, and adapter name. The loader verifies CSV/profile
lineage and adapter hashes rather than silently accepting a mismatched client.

### Speaker emphasis

The three partitions are reused across personas. This supports paired comparisons, but it
does not create new independent source emails. Test reference replies already exist as authored
data; the test partition remains sealed from model evaluation and tuning, not from dataset
construction.

### Evidence

- [Reviewed data manifest](../../data/manual_full_response/MANIFEST.json)
- [Client registry](../../config/persona_registry.json)
- [Persona profiles](../../data/personalities/)
- [Notebook 01: data and routing](../../notebooks/01_email_data_and_routing.ipynb)
- [Notebook 04: persona preparation](../../notebooks/04_persona_response_data.ipynb)

## Slide 3 - Train independently; preserve lineage

### Classification stage

| Setting | Configuration |
|---|---|
| Bases, separate runs | Qwen2.5-0.5B-Instruct; Llama-3.1-Nemotron-Nano-8B-v1 |
| Adapters per base | Generalist, operations, finance, travel |
| Epochs / context | 2 / 512 tokens |
| LoRA | Rank 8, alpha 16, dropout 0.05, `q_proj` and `v_proj` |
| Optimizer settings | Learning rate `2e-4`, batch 1, accumulation 8 |
| Selection | Lowest validation loss; best checkpoint restored |
| Generation contract | Strict JSON label array |
| Routing | CPU TF-IDF plus one-vs-rest logistic regression |

Specialists saw every training email. Off-domain targets were empty arrays, preserving negative
examples. The router used subject/body, not inference-time ground-truth labels. Thresholds were
selected on validation, so those results are development evidence, not untouched test results.

### Persona stage

| Setting | Completed run |
|---|---|
| Base | `Qwen/Qwen2.5-3B-Instruct` |
| Revision | `aa8e72537993ba99e69dfaafa59ed015b17504d1` |
| Hardware | NVIDIA RTX 3090, 24 GiB |
| Precision | BF16 |
| Client adapters | Ten independent runs, sequentially executed |
| Train / validation per client | 1,473 / 312 |
| Epochs / context | 1 / 1,024 tokens |
| LoRA targets / rank | `q_proj`, `v_proj` / 8 |
| Learning rate | `2e-4` |
| Batch / accumulation | 1 / 8 |
| Loss | Completion-only; prompt and padding masked |
| Initialization | Same pinned frozen base, fresh adapter and optimizer per client |
| Checkpoint selection | Lowest validation loss |
| Sum of recorded adapter-training elapsed times | 96.6882 minutes |
| Inference | Greedy, up to 192 new tokens; same prompt for base and adapted modes |

The approximately 97 minutes covers recorded training elapsed time, not total project time,
reference authoring, downloads, setup, or generation evaluation. The Qwen 3B choice is a
practical local model, not the winner of a controlled reply-quality model-selection study.

Each Qwen 3B LoRA weights file is about 7.05 MiB. A full client directory is about 43.5 MiB
including tokenizer assets and a retained checkpoint. Base weights live separately in the
Hugging Face cache. Multi-adapter storage savings are plausible, but memory/concurrency savings
were not benchmarked here.

### Reproducibility controls

- Pinned model and dataset revisions.
- Client registry and CSV/profile hashes.
- Completion-only loss and independently initialized adapters.
- Validation-selected checkpoints and saved training histories.
- Manifest verification before inference.
- Saved ordered evaluation IDs and resumable prediction contracts.
- Separate full and smoke artifact roots; smoke scores are not used as quality evidence.

### Evidence

- [Persona pipeline result](../../artifacts/persona-qwen2.5-3b-full/persona_pipeline/result.json)
- [Maya training manifest](../../artifacts/persona-qwen2.5-3b-full/persona_adapters/maya-chen/manifest.json)
- [Sequential pipeline implementation](../../email_workshop/persona_pipeline.py)
- [Notebook 05: persona training](../../notebooks/05_train_persona_adapter.ipynb)
- [Adapter reuse guide](../../artifacts/README.md)

## Slide 4 - Results: separate validation from diagnostics

### A. Completed classification validation

All strategies below use the same 312 validation emails within each base-model experiment.
Micro-F1 pools label decisions; macro-F1 weights each label equally. Exact match requires the
complete predicted label set to match. Invalid output is measured against the strict parser.

| Base / strategy | Micro-F1 | Macro-F1 | Exact match | Invalid output | Calls/email |
|---|---:|---:|---:|---:|---:|
| Qwen 0.5B / base | 0.4517 | 0.3711 | 20.83% | 11.86% | 1.000 |
| Qwen 0.5B / generalist | 0.8028 | 0.7252 | 67.63% | 0.32% | 1.000 |
| Qwen 0.5B / all specialists | 0.8020 | 0.7343 | 66.67% | 0.96% | 3.000 |
| Qwen 0.5B / routed specialists | 0.8004 | 0.7321 | 66.67% | 0.32% | 1.032 |
| Nemotron 8B / base | 0.1340 | 0.1259 | 5.13% | 40.38% | 1.000 |
| Nemotron 8B / generalist | 0.8465 | 0.7967 | 73.72% | 0.00% | 1.000 |
| Nemotron 8B / all specialists | 0.8142 | 0.7568 | 69.23% | 0.00% | 3.000 |
| Nemotron 8B / routed specialists | 0.8020 | 0.7454 | 67.95% | 0.00% | 1.032 |

**Interpretation:** the generalist had the highest micro-F1 for both tested bases. Qwen all-
specialists had slightly higher macro-F1 than its generalist, showing that the answer depends
on the metric. Routing reduced specialist calls by 65.6%, from 3.000 to 1.032 calls/email.
That is a call-count reduction, not a measured 65.6% end-to-end latency or cost reduction.

Nemotron base scores are specific to this strict prompting/parsing setup and its high invalid-
output rate; they are not a general ranking of pretrained model capability. Prompt robustness,
output formatting, model size, and runtime differ across models. No multi-seed uncertainty
estimate or final-test comparison has been completed.

#### How micro-F1 and macro-F1 are computed

Each email can have multiple labels. The evaluator represents both the expected and predicted
label sets as binary matrices: 312 email rows x 10 label columns. A `1` means that label is
present; a `0` means it is absent. For each label, count across emails:

- **True positives (TP):** the label was expected and predicted.
- **False positives (FP):** the label was predicted but not expected.
- **False negatives (FN):** the label was expected but not predicted.

Predicting a label's absence correctly is a true negative, which does not enter the F1 formula.
An email can contribute multiple counts: if its expected labels are Billing and Complaint,
but the prediction is Billing and Sales, it contributes one TP (Billing), one FN (Complaint),
and one FP (Sales).

For any set of counts:

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
          = 2 * TP / (2 * TP + FP + FN)
```

**Micro-F1: pool counts first, then calculate one F1.** Sum TP, FP, and FN across all ten
labels before applying the formula:

```text
Micro-F1 = 2 * sum(TP) / (2 * sum(TP) + sum(FP) + sum(FN))
```

This measures the overall balance of correct, extra, and missed label assignments. Frequent
labels generally have more influence because they contribute more assignments. It is not an
average of per-email F1 scores and is not the percentage of emails classified perfectly.

**Macro-F1: calculate each label's F1 first, then average equally.**

```text
F1_label = 2 * TP_label / (2 * TP_label + FP_label + FN_label)
Macro-F1 = (F1_label_1 + ... + F1_label_10) / 10
```

Each label receives one-tenth of the weight, regardless of how common it is. Macro-F1 is the
mean of label-level F1 scores, not the F1 calculated from mean precision and mean recall.

**Worked example (two illustrative labels, not the experiment's measured counts):**

| Label | TP | FP | FN | Label F1 |
|---|---:|---:|---:|---:|
| Billing | 8 | 2 | 2 | `16 / (16 + 2 + 2) = 0.80` |
| Complaint | 1 | 1 | 2 | `2 / (2 + 1 + 2) = 0.40` |
| Pooled counts | 9 | 3 | 4 | Used for micro-F1 |

- **Micro-F1:** `18 / (18 + 3 + 4) = 0.72`.
- **Macro-F1:** `(0.80 + 0.40) / 2 = 0.60`.

The difference reveals that performance on the less frequent Complaint label is weaker,
which the pooled score obscures. In the actual table, Qwen generalist micro-F1 of 0.8028 and
macro-F1 of 0.7252 likewise summarize different views; per-label results are needed to identify
which labels are weaker. Neither score is ordinary accuracy.

**Implementation details:** [the evaluator](../../email_workshop/evaluation.py) uses
`sklearn.metrics.f1_score` with `average="micro"` or `average="macro"` and `zero_division=0`.
Undefined scores are set to zero; a label with no expected or predicted positives therefore
contributes zero to macro-F1. All validation emails remain in scoring, including those with
format errors. An invalid response contributes no parsed labels from that call; valid outputs
from other specialist calls on the same email are retained. Invalid-output rate is reported
separately, rather than excluding those emails and inflating the F1 scores.

**Presentation-ready answer:** "Micro-F1 pools all label decisions before calculating F1.
Macro-F1 calculates F1 separately for each label and averages them equally. We report both
because strong performance on common labels can hide weak performance on less frequent ones."

### B. Persona training diagnostics

| Persona | Train loss | Best validation loss |
|---|---:|---:|
| Maya | 2.6614 | 2.3295 |
| Daniel | 2.5344 | 2.1631 |
| Priya | 1.9169 | 1.7169 |
| Lucas | 2.4426 | 2.3493 |
| Amina | 2.2535 | 2.0180 |
| Jordan | 2.1615 | 1.7301 |
| Elena | 2.9110 | 2.5423 |
| Marcus | 2.6546 | 2.2416 |
| Sofia | 2.0581 | 1.6910 |
| Noah | 1.7533 | 1.4523 |

Loss evaluates reference-token prediction, not persona authenticity or truth. Training loss
is an aggregate over training; validation loss is measured at an evaluation checkpoint. They
are not directly comparable estimates of the same distribution, and losses across personas
should not be used to rank persona quality.

#### What completion-only causal-language-model loss means

**Plain English:** show the model an email and its reference reply, then train it to predict
each reply token from the prompt and preceding reference tokens. Score only the completion,
not reproduction of the prompt.

| Term | Meaning |
|---|---|
| Causal | Each prediction uses preceding tokens, never future tokens. |
| Language model | The model assigns probabilities to possible next tokens. |
| Loss | A penalty for assigning low probability to the reference next token; lower is better. |
| Completion-only | Only answer tokens contribute to the loss; prompt tokens supply context but are not scored. |

**Illustrative training example:**

```text
SYSTEM: You are Maya. Reply professionally and briefly.
USER: Please confirm receipt of invoice 123.
ASSISTANT: We received your invoice.
```

The system instruction and incoming email form the prompt. The reference reply is the
completion. For illustration, treat each word below as one token; real tokenization may split
words and punctuation differently.

| Context available | Reference next token | Scored? |
|---|---|---|
| Earlier prompt tokens | Next prompt token | No |
| Full prompt and assistant-start marker | `We` | Yes |
| Full prompt + `We` | `received` | Yes |
| Full prompt + `We received` | `your` | Yes |
| Full prompt + `We received your` | `invoice.` | Yes |

The prompt is still read and conditions the answer. "Not scored" does not mean "ignored."
During training, the preceding answer tokens come from the reference, a method called
**teacher forcing**. During free-running generation, the model instead continues from its
own generated tokens.

**How the penalty is calculated:** next-token cross-entropy is the negative natural logarithm
of the probability assigned to the reference token:

```text
Token loss = -ln(P(reference token | prompt, preceding reference tokens))
Mean completion loss = sum(scored token losses) / number of scored tokens
```

| Reference token | Illustrative probability | Token loss |
|---|---:|---:|
| `We` | 0.50 | 0.693 |
| `received` | 0.80 | 0.223 |
| `your` | 0.25 | 1.386 |
| `invoice.` | 0.50 | 0.693 |

For these four illustrative tokens, mean loss is
`(0.693 + 0.223 + 1.386 + 0.693) / 4 = approximately 0.749`.
The largest penalty is for `your`, because the model assigned it the lowest probability.
This is an example calculation, not a reconstruction of any reported training loss.

**How our implementation masks the prompt:**

```text
input_ids = prompt_tokens + reference_reply_tokens + [EOS]
labels    = [-100 for each prompt token] + reference_reply_tokens + [EOS]
```

[Persona training preprocessing](../../email_workshop/persona.py) includes an end-of-sequence
(EOS) token in the scored completion, teaching the model when to stop. The causal-LM
implementation shifts predictions and labels internally so each position predicts the next
token. Labels of `-100` are excluded from cross-entropy; the
[completion collator](../../email_workshop/training.py) also uses `-100` for padding labels.
The four-token example above omits EOS for simplicity; the actual loss includes it.
With LoRA, optimization updates the trainable adapter parameters while the base weights remain
frozen.

**What lower loss proves:** the model assigns higher probability to reference tokens given
their context. It does not independently prove factual accuracy, safe behavior, persona
authenticity, or better free-running generation. For example, "Your invoice has been received."
may also be a good reply, but the loss scores the supplied reference wording, "We received
your invoice." It does not directly reward every valid paraphrase.

**Presentation-ready answer:** "We train the adapter to predict the desired reply one token
at a time, using the email and preceding reference tokens as context. Only the reply and its
stop token are scored, not the prompt. Lower loss means better prediction of our reference
replies, not independent proof of reply quality."

### C. Preliminary persona generation diagnostics

Base and adapted generation used identical email IDs and persona prompts. The unadapted base
was already persona-conditioned: the comparison isolates adding LoRA, not adding a persona
prompt. Each client has eight paired validation examples.

| Persona | Token F1: base | Token F1: adapter | ROUGE-L: base | ROUGE-L: adapter |
|---|---:|---:|---:|---:|
| Maya | 0.2323 | 0.2689 | 0.1822 | 0.2223 |
| Daniel | 0.1297 | 0.3234 | 0.1018 | 0.2835 |
| Priya | 0.2696 | 0.4334 | 0.2012 | 0.3517 |
| Lucas | 0.1264 | 0.1836 | 0.1005 | 0.1441 |
| Amina | 0.1281 | 0.2565 | 0.0994 | 0.2238 |
| Jordan | 0.2594 | 0.3683 | 0.1829 | 0.2895 |
| Elena | 0.1324 | 0.3036 | 0.0854 | 0.2380 |
| Marcus | 0.1549 | 0.3779 | 0.1122 | 0.3105 |
| Sofia | 0.2610 | 0.4356 | 0.1879 | 0.3532 |
| Noah | 0.2220 | 0.4010 | 0.1767 | 0.3500 |
| **Equal-weight mean across personas** | **0.1916** | **0.3352** | **0.1430** | **0.2767** |

Means are calculated from unrounded saved metrics, weighting each persona equally. All
personas have eight examples, but these are the **same eight unique incoming emails**.
There are 80 persona-email comparisons and 160 generated outputs, not 80 independent
source-email samples.

- All ten personas improved both mean lexical diagnostics on this subset.
- Non-empty response rate was 100% in both modes.
- Exact reference-match rate was 0% in both modes, which is unsurprising for open-ended replies.
- Mean generated/reference length ratio moved from 1.9809 to 0.8482. Shorter is not automatically
  better; essential content could be omitted.
- Per-persona median latency was lower in the adapted samples, but output lengths also changed.
  This is not a controlled throughput benchmark.

**No confidence interval, population-quality claim, or safety certification should be inferred
from eight emails.** Synthetic references can favor the authoring assistant's style. Lexical
overlap can reward mimicry and penalize valid paraphrases. A label-distribution slice from so
few emails cannot establish broad domain coverage.

### What remains unmeasured

- Full 312-email persona generation validation.
- Human-rated relevance, grounding, actionability, voice, and boundary adherence.
- Human agreement and preference confidence intervals.
- Cross-persona contamination and wrong-adapter behavior.
- Robustness to long threads, prompt injection, altered names, dates, and amounts.
- Live shared-base serving latency, concurrency, memory, and isolation.
- Final performance on the sealed 318-email test partition.

### Evidence

- [Qwen classification run report](../../artifacts/local-full-20261018/2026-10-18-RUN-REPORT.md)
- [Nemotron classification run report](../../artifacts/nemotron-nano-8b-full-20261018/2026-10-18-NEMOTRON-RUN-REPORT.md)
- [Qwen classification metric files](../../artifacts/local-full-20261018/evaluation/)
- [Nemotron classification metric files](../../artifacts/nemotron-nano-8b-full-20261018/evaluation/)
- [Persona generation predictions](../../artifacts/persona-qwen2.5-3b-full/persona_evaluation/)
- [Persona pipeline summaries](../../artifacts/persona-qwen2.5-3b-full/persona_pipeline/result.json)

## Slide 5 - Prove quality before scaling

The following are **proposed next experiments**, not completed results or previously approved
release thresholds.

| Priority | Experiment | Design and measurements | Decision gate |
|---|---|---|---|
| 1 | Full paired validation | All 312 validation emails for all ten personas, identical IDs/prompts/decoding; overlap, length, empty/truncation failures, label slices | Complete coverage and valid lineage before comparing quality |
| 2 | Blinded human quality study | At least two reviewers; randomized A/B/tie; 1-5 anchored relevance, persona, grounding, actionability, boundaries | Pre-register quality margin and acceptable critical-error rate before scoring; report preference CI and agreement |
| 3 | Ablations and negative controls | Same model with persona prompt only; correct versus wrong adapter; one shared reply adapter; shuffled persona association as an optional control | Establish whether persona-specific training adds useful signal beyond prompting and generic reply training |
| 4 | Robustness and grounding | Changed numbers/names/dates, unsupported approvals, long quoted threads, multilingual mail, prompt injection | Review every critical failure; demonstrate no unacceptable regression against base under predeclared rules |
| 5 | Runtime and final test | Benchmark single adapter and verified shared-base server at controlled token lengths/load; freeze model/prompt/thresholds; then test once | Report p50/p95, tokens/s, VRAM, quality and isolation; final 318-email test only after development decisions are frozen |

### Statistical design

Use paired email-level differences. Report distributions and bootstrap confidence intervals,
not just a mean. When aggregating all personas, resample by incoming email and retain its
persona observations together; treating persona-email pairs as independent would overstate
precision. A per-persona analysis can resample emails within that persona.

For human preference use A/B/tie outcomes, record disagreements and adjudication, and report
an appropriate agreement statistic, such as Cohen's kappa for two raters' categorical choices.
Agreement is not correctness. Freeze the rubric and evaluation plan before opening final test
outputs. If changing the system after seeing test results, obtain a new independent holdout.

### Safety and deployment boundaries

Heuristic risk flags are review aids, not safety detectors. An optional independent LLM judge
must be calibrated against human judgments and tested for position bias. Do not send private
mail to an unapproved endpoint. Preserve human approval before sending replies, particularly
for legal, financial, HR, and booking commitments.

Run the evaluation teaching sequence in
[notebook 07](../../notebooks/07_persona_evaluation_techniques.ipynb), following the
[evaluation plan](../PERSONA_EVALUATION_PLAN.md). Its safe cached path has been executed;
that does not imply every optional expensive, embedding, judge, or final-test branch was run.
Its custom character n-gram score is a diagnostic implementation, not necessarily standard
sacreBLEU chrF.

## Walkthrough of the complete process

1. Investigate local LoRA feasibility separately from managed Foundry/NIM support.
2. Pin and inspect the dataset; recognize multi-label supervision.
3. Quarantine conflicting exact duplicates and create stable partitions.
4. Establish base, generalist, specialist, and routed classification comparisons.
5. Smoke-test loading, training, saving, and evaluation before full experiments.
6. Train and validate Qwen 0.5B and Nemotron 8B classification adapters in separate runs.
7. Define ten synthetic profiles and author complete reference replies.
8. Validate response coverage/schema/lineage and commit durable data, not intermediate ledgers.
9. Train independent Qwen 3B persona adapters sequentially with clean initialization.
10. Compare saved base/adapted generations on identical prompts and eight validation IDs.
11. Build the evaluation notebook, staged evaluation plan, and adapter reuse guide.
12. Next: execute broader generation/human/robustness evaluation before final test and deployment.

Historical successful local Nemotron training should not be described as impossible on this
machine. Equally, successful training does not prove support for the same adapter in a managed
NIM profile or Foundry endpoint.

## Reproducibility and reading list

### Exact model identities

| Task/run | Model | Immutable revision |
|---|---|---|
| Classification, Qwen | `Qwen/Qwen2.5-0.5B-Instruct` | `7ae557604adf67be50417f59c2c2f167def9a775` |
| Classification, NVIDIA | `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` | `54641c1611fcff44fa4865626462445e0a153fc7` |
| Persona replies | `Qwen/Qwen2.5-3B-Instruct` | `aa8e72537993ba99e69dfaafa59ed015b17504d1` |

The recorded local training stack includes Python 3.12.10, PyTorch 2.10.0+cu128,
Transformers 4.57.6, and PEFT 0.18.1. Individual manifests remain authoritative.
See [environment setup](../LOCAL_SETUP.md) and
[NVIDIA compatibility findings](../NEMOTRON_LORA_FINDINGS.md).

### Method background

- [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685):
  the parameter-efficient adaptation method.
- [S-LoRA: Serving Thousands of Concurrent LoRA Adapters](https://arxiv.org/abs/2311.03285):
  shared serving research, not a description of a benchmark performed here.
- [Punica: Multi-Tenant LoRA Serving](https://arxiv.org/abs/2310.18547):
  multi-adapter serving architecture and motivation.
- [ROUGE: A Package for Automatic Evaluation of Summaries](https://aclanthology.org/W04-1013/):
  overlap-based evaluation background, with limitations for open-ended replies.
- [Dataset card](https://huggingface.co/datasets/imnim/multiclass-email-classification)
  and [Qwen 3B model card](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct).

### Evidence access and scope

The source repository is [rashmijain02/multi-lora](https://github.com/rashmijain02/multi-lora).
Artifact links in this companion are local and work only when the ignored training outputs are
present. The PowerPoint and companion contain aggregate results, not a redistribution of model
weights or raw emails.

The separately attached CLM evaluation snapshot describes six classes (`forum`, `promotions`,
`social_media`, `spam`, `updates`, `verify_code`) and its attached output is empty. No measured
CLM result is included here, and that taxonomy is not substituted for the ten-label workshop
taxonomy.

No new model training, final-test inference, external generation call, or human evaluation was
performed to prepare this presentation.
