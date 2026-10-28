# Cost model: Copilot models vs local models for the simulation

How much the simulated-corporation work costs in model usage, which models are cheapest, and
whether running models locally saves money. Prices are a **snapshot taken on 2026-10-26**;
re-check them before relying on the numbers (section 7 shows how to recompute).

Related plans: [STORY_PLAN_ENTERPRISE.md](./STORY_PLAN_ENTERPRISE.md) (the arcs and scoring
that drive the workload) and [DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md) (the local stack).

---

## Contents

1. [Summary](#1-summary)
2. [Who pays for what today](#2-who-pays-for-what-today)
3. [How Copilot bills](#3-how-copilot-bills)
4. [Measured cost of one job](#4-measured-cost-of-one-job)
5. [Workload sizes](#5-workload-sizes)
6. [Copilot model comparison](#6-copilot-model-comparison) (6.1: [the same models on Azure Foundry](#61-the-same-models-on-azure-foundry))
7. [How to recompute](#7-how-to-recompute)
8. [DGX Spark (local models)](#8-dgx-spark-local-models)
9. [Recommendation: a tiered setup](#9-recommendation-a-tiered-setup)
10. [Caveats](#10-caveats)
11. [Next step: a cheap model bake-off](#11-next-step-a-cheap-model-bake-off)

---

## 1. Summary

| Question | Answer |
|---|---|
| What does one PersonaDesk job cost today? | About **$0.08** on Claude Opus 5.5 (range $0.045–0.14) |
| A full improvement campaign (about 2,000 jobs)? | About **$156** on Opus 5.5; **$78** on Sonnet 5.5; **$4** on Haiku 5.5 |
| Does a local model save money? | Only versus top-tier models. The cheapest Copilot models cost about the same as local electricity |
| Is Azure Foundry cheaper than Copilot? | Same per-token rates (Global Standard); Foundry's **Flex** tier halves some OpenAI models; Gemini is not on Foundry (section 6.1) |
| Is buying a DGX Spark worth it for cost alone? | No: about 30–45 Opus campaigns to pay back, never against Haiku 5.5 |
| What would make local worth it? | **Trained SLMs** reaching Opus quality: a campaign drops from about $250 hosted to about $3 on the Spark (section 8.1) |
| Why go local, then? | LoRA training (needs local anyway), privacy, no usage limits, learning |

---

## 2. Who pays for what today

| Component | Model / service | Who pays |
|---|---|---|
| PersonaDesk profiles `pd-priya`, `pd-daniel`, `pd-noah` | Provider `copilot`, model `claude-opus-5.5` | Your Copilot plan (via your `gh` sign-in) |
| Context compression | `auto` (believed to be the same provider; not verified) | Probably your Copilot plan |
| Hermes `default` profile | `anthropic/claude-opus-4.6` | Whichever Anthropic key it uses; not used by PersonaDesk |
| Mail server, Thunderbird, deterministic checks | No model | Free |
| Writer LoRA adapters, CLM encoder | Local vLLM ([DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md)) | Your hardware and electricity |

Check what a profile uses with `hermes -p pd-priya config show` and `hermes profile list`.

---

## 3. How Copilot bills

- Since June 2026, Copilot bills model use in **GitHub AI Credits**: 1 credit = $0.01.
- Each interaction is priced by tokens: **input**, **cached input** (reused prompt prefix),
  **cache write** (Anthropic and newer OpenAI models) and **output**.
- Plans include a monthly credit allowance; usage above it is billed at the same per-token
  rates. Check your plan and allowance on your Copilot billing page.
- Official price list: <https://docs.github.com/en/copilot/reference/copilot-billing/models-and-pricing>.

---

## 4. Measured cost of one job

Source: `hermes -p pd-priya insights --days 30` on 2026-10-26 (15 sessions, all Opus 5.5).
`pd-daniel` and `pd-noah` had no recorded sessions; their jobs are assumed similar.

| Measure | Total (15 sessions) | Per job |
|---|---|---|
| Fresh input tokens | 93,174 | about 6,200 |
| Output tokens | 12,512 | about 830 |
| Cached tokens (total − input − output) | 303,668 | about 20,200 |
| Total tokens | 409,354 | about 27,300 |
| Messages | 143 | about 10 (about 4 tool calls) |

Insights do not split cached tokens into cheap **reads** and expensive **writes**. The
estimates assume **one third writes, two thirds reads**; all-reads and all-writes give the
range.

Per-job cost formula (prices per million tokens):

```text
cost = (6,212 × input + 13,497 × cached + 6,748 × cache_write + 834 × output) / 1,000,000
```

Claude Opus 5.5 ($4 input, $0.20 cached, $5 cache write, $20 output) gives **$0.078**.

---

## 5. Workload sizes

| Workload | Jobs | Source |
|---|---|---|
| Today's 9 scenarios, one pass | 9 | `fixtures/` |
| First enterprise arc | about 7 | [STORY_PLAN_ENTERPRISE.md](./STORY_PLAN_ENTERPRISE.md) section 5 |
| Three legal arcs | about 24 | `STORY_PLAN_LEGAL_*.md` |
| All planned arcs and scenarios, one pass | about 120 | Enterprise catalogue + legal arcs + fixtures |
| One improvement round (baseline + candidate, dev + validation) | about 200 | Hill-climbing loop |
| Campaign of 10 rounds | about 2,000 | |
| Judge scoring | about 5,000 tokens per beat | Adds about 15% on the same model |
| Noise mail, if intake classifies it | about 5,000 tokens per message | Avoid with a cheap classifier |

---

## 6. Copilot model comparison

Per-job profile from section 4, prices from the official page on 2026-10-26. Sorted from most
to least expensive.

| Model | Per job | One pass (120) | One round (200) | Campaign (2,000) |
|---|---:|---:|---:|---:|
| GPT-6 Astra | $0.202 | $24.20 | $40.33 | $403 |
| Claude Fable 5.1 | $0.192 | $22.99 | $38.31 | $383 |
| Claude Opus 5 / 4.8 | $0.101 | $12.10 | $20.17 | $202 |
| GPT-5.6 Sol | $0.081 | $9.68 | $16.13 | $161 |
| **Claude Opus 5.5 (current)** | **$0.078** | **$9.36** | **$15.59** | **$156** |
| Claude Sonnet 4.6 | $0.061 | $7.26 | $12.10 | $121 |
| GPT-5.6 Terra | $0.042 | $5.04 | $8.40 | $84 |
| GPT-6 Sol | $0.040 | $4.84 | $8.07 | $81 |
| Claude Sonnet 5 | $0.040 | $4.84 | $8.07 | $81 |
| GPT-6.1 Sol | $0.039 | $4.68 | $7.80 | $78 |
| Claude Sonnet 5.5 | $0.039 | $4.68 | $7.80 | $78 |
| Kimi K3 | $0.037 | $4.47 | $7.44 | $74 |
| Grok 4.5 / 4.6 / 4.7 | $0.028 | $3.31 | $5.51 | $55 |
| GPT-5.3-Codex | $0.026 | $3.13 | $5.22 | $52 |
| Gemini 4 Argon (promo until 2026-12-01) | $0.023 | $2.73 | $4.56 | $46 |
| Claude Haiku 4.5 | $0.020 | $2.42 | $4.03 | $40 |
| GPT-6.1 Terra | $0.020 | $2.34 | $3.90 | $39 |
| Gemini 3.8 Flash (promo until 2026-12-31) | $0.009 | $1.12 | $1.86 | $19 |
| GPT-5.6 Luna | $0.004 | $0.50 | $0.84 | $8 |
| GPT-5.4 nano | $0.003 | $0.32 | $0.54 | $5 |
| MAI-Code-1.1-Flash | $0.003 | $0.32 | $0.53 | $5 |
| GPT-6 Luna | $0.002 | $0.24 | $0.40 | $4 |
| **Claude Haiku 5.5** | **$0.002** | **$0.24** | **$0.40** | **$4** |

Models without a cache-write price are charged their cached-input rate for those tokens.

### 6.1 The same models on Azure Foundry

Foundry (the V2 hosting track in
[PROPOSAL.md](../PROPOSAL.md#14-v2-azure-foundry-managed-hermes-harness)) is billed
separately from Copilot, on your Azure subscription.

How Foundry bills:

- **Claude**: through an Azure Marketplace offer in Claude Consumption Units, converted from
  **Anthropic's published per-token rates**. These rates equal the Copilot rates in section 6.
- **OpenAI, MAI, xAI, Kimi (Fireworks)**: per-token Azure meters. The **Global Standard** rates
  checked here equal Copilot's. **Data Zone** (data kept in one geography) costs 10% more.
  Some OpenAI models also have a **Flex** tier at about half price, with slower and less
  predictable latency, which suits batch simulation runs.
- **Fine-tuned models** add training hours and an hourly hosting fee while deployed.

Sources (checked 2026-10-26):
[Foundry Models sold by Azure](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure),
[Claude models in Foundry](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/claude-models),
[Claude CCU billing](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/claude-models-billing),
[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), and the public
[Azure Retail Prices API](https://prices.azure.com/api/retail/prices) (`serviceName eq 'Foundry Models'`).

Campaign = 2,000 jobs with the section 4 profile. "—" means not available or no price found.

| Model | On Foundry? (hosting) | Copilot campaign | Foundry Global campaign | Foundry Data Zone (+10%) | Foundry Flex campaign |
|---|---|---:|---:|---:|---:|
| GPT-6 Astra | Yes (Azure) | $403 | $403 | — | — |
| Claude Fable 5.1 | Preview (Anthropic-hosted only) | $383 | $383 | — | — |
| Claude Opus 5 / 4.8 | Yes (Azure or Anthropic) | $202 | $202 | — | — |
| GPT-5.6 Sol | Yes (Azure) | $161 | $161 | $177 | not checked |
| **Claude Opus 5.5 (current)** | Yes (Azure or Anthropic) | **$156** | **$156** | — | — |
| Claude Sonnet 4.6 | Yes (Anthropic-hosted only) | $121 | $121 | — | — |
| GPT-5.6 Terra | Yes (Azure) | $84 | $84 | $92 | $42 |
| GPT-6 Sol | Yes (Azure) | $81 | $81 | — | — |
| Claude Sonnet 5 | Yes (Azure or Anthropic) | $81 | $81 | — | — |
| GPT-6.1 Sol | Yes (Azure) | $78 | $78 | $86 | $39 |
| Claude Sonnet 5.5 | Yes (Azure or Anthropic) | $78 | $78 | — | — |
| Kimi K3 | Azure price meter (Fireworks), not in the docs model list; check the catalog | $74 | $74 | $82 | — |
| Grok 4.6 / 4.7 | Listed; no price meter found | $55 | not found | — | — |
| Grok 4.5 | **No** (4.6 and 4.7 replace it) | $55 | — | — | — |
| GPT-5.3-Codex | Yes (Azure) | $52 | $52 | $57 | — |
| Gemini 4 Argon | **No** | $46 | — | — | — |
| Claude Haiku 4.5 | Yes (Azure or Anthropic) | $40 | $40 | — | — |
| GPT-6.1 Terra | Listed; no price meter found | $39 | not found | — | — |
| Gemini 3.8 Flash | **No** | $19 | — | — | — |
| GPT-5.6 Luna | Yes (Azure) | $8 | $8 | $9 | $4 |
| GPT-5.4 nano | Yes (Azure) | $5 | $5 | $6 | — |
| MAI-Code-1.1-Flash | Yes, metered as a fine-tuned deployment: same token rates plus $0.36 per hour hosting | $5 | $5 + hosting | — | — |
| GPT-6 Luna | Yes (Azure) | $4 | $4 | — | — |
| **Claude Haiku 5.5** | Yes (Azure or Anthropic) | **$4** | **$4** | — | — |

Takeaways:

- On per-token price alone, Foundry Global Standard and Copilot cost the same for every model
  priced here.
- Foundry differences that matter: **Flex halves the cost** for supported OpenAI models;
  Data Zone adds 10%; Claude bills through Azure Marketplace (MACC-eligible); usage is not
  counted against a Copilot plan allowance.
- Claude Data Zone rates are not on the Azure meters (Claude is billed in CCU); check the
  Foundry portal **Pricing** tab.

---

## 7. How to recompute

1. Measure your own profile after a run:

   ```powershell
   hermes -p pd-priya insights --days 7
   ```

   Divide input, output and (total − input − output) by the number of sessions.

2. Copy current prices from the official page (section 3).
3. Run this from `workshops/personal-agent-multilora/`, editing the numbers and the model
   list:

   ```powershell
   @'
   fin, out, cache = 6212, 834, 20245          # per-job tokens from step 1
   cw, cr = cache / 3, cache * 2 / 3           # assumed write/read split
   models = [  # name, input, cached, cache_write (None = cached rate), output
       ("Claude Opus 5.5", 4, 0.20, 5, 20),
       ("Claude Sonnet 5.5", 2, 0.10, 2.5, 10),
       ("Claude Haiku 5.5", 0.10, 0.01, 0.125, 0.50),
   ]
   for name, i, c, w, o in models:
       w = c if w is None else w
       job = (fin * i + cr * c + cw * w + out * o) / 1e6
       print(f"{name:20s} job ${job:.4f}  pass ${job*120:6.2f}  campaign ${job*2000:7.2f}")
   '@ | uv run python -
   ```

### 7.1 Where every number comes from

Every figure in this document is one of four kinds. Only **measured** and **sourced** inputs
are facts; everything else follows from them by arithmetic or is an assumption you should
replace with your own measurement.

| Kind | Inputs | How to check |
|---|---|---|
| **Measured** (this project) | Tokens per job: 6,212 input, 834 output, 20,245 cached (section 4) | Re-run `hermes -p pd-priya insights --days 30` |
| **Sourced** (official page) | Copilot per-token prices (section 6); Foundry availability and prices (section 6.1) | The official pages and Azure Retail Prices API linked in sections 3 and 6.1 |
| **Sourced** (third-party, unverified) | Spark price $4,699–6,950, 140 W TDP / 240 W supply, about 40 tokens/s single stream | Vendor listings and reviews; replace with your own measurements (section 8.9) |
| **Assumed** | Cache split 1/3 write, 2/3 read; 2,000 jobs per campaign; 1,000 noise messages; 100 generated scenarios; writer call 3,000 in / 400 out; triage 5,000 in / 100 out per message; judge = 15% of controller; 200 W; $0.30/kWh; 60 s per job (120B), 20 s (SLM); 4 training runs of 2 h; 5% hosted judge audit | Change them in the script below |
| **Computed** | All costs, totals, yearly figures and payback times | The script below reproduces them |

Script for sections 8.1 and 8.5–8.6 (run from `workshops/personal-agent-multilora/`):

```powershell
@'
fin, out, cache = 6212, 834, 20245; cw, cr = cache / 3, cache * 2 / 3
P = {"Opus 5.5": (4, .20, 5, 20), "Sonnet 5.5": (2, .10, 2.5, 10),
     "Haiku 5.5": (.10, .01, .125, .50)}
JOBS, NOISE, SCEN = 2000, 1000, 100
for m, (i, c, w, o) in P.items():
    job = (fin * i + cr * c + cw * w + out * o) / 1e6
    ctrl = job * JOBS
    writer = (3000 * i + 400 * o) / 1e6 * JOBS
    triage = (5000 * i + 100 * o) / 1e6 * NOISE
    judge, gen = 0.15 * ctrl, job * SCEN
    tot = ctrl + writer + triage + judge + gen
    print(f"{m:11s} ctrl ${ctrl:.1f} writer ${writer:.1f} triage ${triage:.1f} "
          f"judge ${judge:.1f} gen ${gen:.1f} TOTAL ${tot:.1f} per year at 1/4/10 per month: "
          f"${tot*12:,.0f} ${tot*48:,.0f} ${tot*120:,.0f}")
kw, rate = 0.2, 0.30
e = lambda sec: sec / 3600 * kw * rate          # electricity in dollars
print(f"Spark 120B controller ${e(JOBS * 60):.2f}")
slm, train = e(JOBS * 20), 4 * 2 * kw * rate
audit = 0.05 * 0.15 * 155.9                       # 5% of the Opus judge cost
print(f"SLM controller ${slm:.2f} training ${train:.2f} audit ${audit:.2f} "
      f"total ${slm + 0.30 + 0.05 + 0.20 + train + audit:.2f}")
for n in (1, 4, 10):
    s = (249.1 - 2.87) * n                        # monthly saving vs Opus
    print(f"payback at {n}/month: {5000 / s:.1f}-{7000 / s:.1f} months")
'@ | uv run python -
```

The writer ($0.30), triage ($0.05) and judge ($0.20) SLM electricity figures are assumed
from relative workload size, not computed; measure them per section 8.9.

---

## 8. DGX Spark (local models)

The local option for this project is an NVIDIA **DGX Spark** running the stack in
[DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md). This section prices it against Copilot. All Spark
figures are **estimates** from third-party reviews and the guide's memory plan, not
measurements on this project's machine; section 8.9 shows how to measure them.

### 8.1 Motivation: hosted frontier models vs trained SLMs on the Spark

Hosting is not the question: everything in this project **can** run on the Spark. The
question is whether **small language models (SLMs, about 3–8B parameters) trained for each
task** can match the hosted frontier models (Copilot today, or the same models on Azure
Foundry for V2 in [PROPOSAL.md](../PROPOSAL.md#14-v2-azure-foundry-managed-hermes-harness)).
The table puts a price on that question, task by task.

Assumptions:

- One campaign = 2,000 jobs (section 5) plus about 1,000 noise or attack messages to triage.
- Copilot and Foundry are shown as **separate columns** using the prices in sections 6 and
  6.1. For Claude Opus 5.5 they are the same per-token rates. Foundry adds options Copilot
  does not have: Data Zone deployments (+10%) and a cheaper Flex tier for some OpenAI models.
- Spark costs are electricity only (owned machine, 200 W, $0.30/kWh). SLM time per job is
  assumed to be about a third of the 120B-class model's.
- Rows marked *estimate* have not been measured: there is no separate hosted writer or judge
  run yet.

| Task in the simulation | Copilot (Opus 5.5): cost per campaign | Foundry (Opus 5.5, Global / Data Zone): cost per campaign | Spark, large open model, no training (120B class) | Spark, **trained SLM** (target) | SLM cost per campaign | How the SLM is trained | Parity gate before switching |
|---|---|---|---|---|---|---|---|
| **Controller**: reads mail, calls tools, routes the draft | **$156** (measured profile); Sonnet 5.5: $78 | **$156** / $172; Sonnet 5.5: $78 / $86 | About $2; 33 h single stream, 6–10 h concurrent | 7–8B tool-calling model + LoRA | about $0.70 | Fine-tune (SFT) on recorded, human-approved Hermes sessions from hosted runs: tool calls and final actions (distillation) | Same pass rate as Opus on the validation split; **zero** safety failures; tool-call errors and `no_draft` no worse |
| **Writer**: drafts in the persona's voice | As a separate draft call: about **$40** *(estimate: 3,000 in, 400 out per job)* | about $40 / $44 | Not needed | **Already an SLM**: Qwen2.5-7B + one rank-8 LoRA per persona | about $0.30 | Already done: persona adapters ([DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md) §5) | Already gated by releases (guide §8) |
| **Triage / noise and attack classifier** | At about 5,000 tokens per message: about **$22** per 1,000 messages | about $22 / $24 | About $0.20 | **Already an SLM**: Qwen3-8B encoder + CLM head (guide §7) | about $0.05 | Labelled fixture and noise mail; story beats add new labels | Recall on attack mail ≥ hosted; no real mail dropped |
| **Judge**: scores each beat against the rubric | At about 15% of controller: about **$23** *(estimate)*; Sonnet 5.5 about $12 | about $23 / $26 | About $0.30 | 3–8B judge from a **different family** from the controller | about $0.20 | LoRA on human review verdicts plus frontier-judge labels | Agreement with human labels at least that of the hosted judge on the sealed set; re-audit a 5% sample on a hosted judge (about $1) |
| **Scenario generation** (recipe Path C) | About **$8** for about 100 scenarios *(estimate)* | about $8 / $9 | About $0.10 | Keep hosted or 120B; low volume, creativity matters | — | Not worth training | Human review of every generated scenario (already required) |
| **LoRA training runs** | Not available | Example, MAI-Code-1.1-Flash reinforcement fine-tuning: $80 per hour (Global), so 4 runs of 2 h ≈ **$640**; serving the tuned model adds $0.36 per hour (≈ $263 per month if left deployed) | — | Spark | about $0.50 (a few runs of about 2 h) | — | — |
| **Total per campaign** (inference) | **about $250** (Opus) · about $125 (Sonnet 5.5) · about $6.40 (Haiku 5.5) | **about $250** / $274 (Opus) · about $125 / $137 (Sonnet 5.5) · about $6.40 (Haiku 5.5, Global) | **about $3** | | **about $3** (including the $1.17 hosted judge audit) | | |

What the totals mean at different volumes (hardware bought once for about $5,000–7,000):

| Campaigns per month | Hosted Opus per year | Hosted Sonnet 5.5 per year | Hosted Haiku 5.5 per year | Spark SLMs per year (electricity) | Spark payback vs Opus |
|---:|---:|---:|---:|---:|---:|
| 1 | about $3,000 | about $1,500 | about $77 | about $35 | about 2 years |
| 4 | about $12,000 | about $6,000 | about $310 | about $140 | about 5–7 months |
| 10 | about $30,000 | about $15,000 | about $770 | about $350 | about 2–3 months |

How to read this:

- The saving is real only if the trained SLMs reach **Opus-level quality**: Spark SLMs cost
  about the same as the cheapest hosted model (Haiku 5.5), so the goal is "Opus quality at
  Haiku cost". If Haiku 5.5 already passes the gates, it is the cheaper path.
- The **controller** is where almost all the money is (about 60% of the hosted total) and is
  the hardest to train: it must make correct tool calls over several turns. It is the main
  experiment.
- The **writer** and **classifier** are already SLMs, so they already show the pattern: a
  small model trained for one narrow task.
- Hosted runs are not wasted: every approved Opus session becomes training data for the
  controller SLM. Spend on hosted models to label, then train, then switch per task once the
  parity gate passes.

### 8.2 What runs on the Spark, and what it replaces

| Role | Spark process (guide section) | Replaces on Copilot? | Notes |
|---|---|---|---|
| Controller (Hermes's model: plans, calls tools) | vLLM on `:8000` (§3) | **Yes**: the `claude-opus-5.5` calls priced in section 6 | The only role that costs Copilot credits today |
| Writer (persona voice, LoRA adapters) | vLLM Multi-LoRA on `:8001` (§6) | No; Copilot cannot serve your adapters | Needed for the LoRA loop either way |
| CLM encoder + API | vLLM pooling `:8090`, `clm-serve :8700` (§7) | No | Classification backend |
| LoRA training | PyTorch container (§5) | No | Runs only on local hardware |
| Judge and noise classifier (proposed) | A second small model, or the controller | **Yes**: section 5's judge and classifier tokens | Must differ from the controller for judging |

So the Spark is **already needed** for the writer, encoder and training. Using it as the
controller too adds no hardware cost, only electricity and time.

### 8.3 Hardware variants and what fits

From the guide's memory budget (§1):

| Variant | Price (third-party, Oct 2026; verify) | Controller | Everything resident at once? |
|---|---|---|---|
| 128 GB | about $4,699–6,950 | NVIDIA-recommended tool-calling model, NVFP4, about 51 GB (`0.40`) | Yes: controller + writer 7B + encoder + OS |
| 64 GB OEM | about $4,999 | Smaller controller at `0.45` | No: run phases one at a time (controller + writer, then classification, then training) |

During **LoRA training** the writer (and maybe the encoder) is stopped, so simulation runs
that need the writer pause while you train.

### 8.4 Speed assumptions

| Item | Value | Note |
|---|---|---|
| Controller decode, single stream | about 40 tokens/s (gpt-oss-120b class) | Reviews report about 33–60 tokens/s |
| Aggregate decode, many concurrent jobs | up to about 860 tokens/s at 256 concurrent requests | Realistic for this project: 4–8 concurrent jobs |
| Output per job | about 1,700 tokens | 830 measured visible output plus an allowance for reasoning tokens |
| Time per job, single stream | about 60 s | Decode plus prefill of about 6,000 fresh tokens per call |
| Smaller 20–30B mixture-of-experts controller | about 2–3× faster | More likely to fail tool calls |

### 8.5 Running cost (you already own the Spark)

Assumes 200 W under load (GB10: 140 W TDP, 240 W supply) and **$0.30/kWh**; use your own
rate.

| Workload | Jobs | Wall-clock, single stream | Wall-clock, 4–8 concurrent (estimate) | Energy | Electricity |
|---|---:|---:|---:|---:|---:|
| Today's 9 scenarios | 9 | about 9 min | about 2–3 min | 0.03 kWh | about $0.01 |
| One full pass | 120 | about 2 h | about 20–40 min | 0.4 kWh | about $0.12 |
| One improvement round | 200 | about 3.3 h | about 40–60 min | 0.7 kWh | about $0.20 |
| Campaign | 2,000 | about 33 h | about 6–10 h | 6.7 kWh | about **$2** |

Idle power is not included: measure it (section 8.9) if the Spark stays on all day.

### 8.6 Ownership cost (buying a Spark for this)

| Item | Value |
|---|---|
| Price | about $5,000–7,000 |
| Written off over 3 years | about **$130–190 per month**, used or not |

| Compared with (per campaign) | Copilot cost | Campaigns to pay back about $5,000 |
|---|---:|---:|
| Claude Opus 5.5 | $156 | about 30–45 |
| Claude Sonnet 5.5 | $78 | about 65–90 |
| Claude Haiku 5.5 / GPT-6 Luna | $4 | never |

### 8.7 Spark vs Copilot, side by side

| Factor | DGX Spark (owned) | Copilot Opus 5.5 | Copilot Haiku 5.5 |
|---|---|---|---|
| Campaign cost | about $2 electricity | about $156 | about $4 |
| Campaign wall-clock | about 6–10 h (concurrent) | Mostly limited by Hermes and rate limits | Same |
| Tool-call reliability | Depends on the model; must pass the guide's §3 check | High | Lower than Opus; bake-off needed |
| Data leaves the machine | No | Yes (to GitHub and the model provider) | Yes |
| Usage limits | None | Plan allowance, then billed | Same |
| Serves LoRA writer, encoder, training | Yes | No | No |
| Setup effort | High (guide §§0–7) | None (already working) | Change model per profile |

### 8.8 Pointing PersonaDesk profiles at the Spark

1. Bring up the controller and verify tool calling ([DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md)
   §3).
2. From a laptop, open the SSH tunnel so `http://127.0.0.1:8000/v1` reaches the Spark (guide
   §10). Never expose the port on `0.0.0.0`.
3. Switch one profile at a time with `hermes -p pd-priya model`, choose **Custom endpoint**,
   enter `http://127.0.0.1:8000/v1` and the served model id.
4. Put the model in the run label (`--source-key "spark-<model>:<fixture>"`) so scores stay
   comparable with Copilot runs.
5. Switch back the same way to compare.

### 8.9 Measuring the real numbers

| What | How |
|---|---|
| Tokens per job | `hermes -p pd-priya insights --days 1` after a run (local runs show tokens, no price) |
| Time per job | Note wall-clock for the 9-scenario pass; divide by 9 |
| Power under load and idle | A plug-in wall power meter on the Spark |
| Electricity cost | kWh from the meter × your tariff |
| Quality | Pass rate and safety failures on the same 9 scenarios (section 11) |

Replace the estimates in sections 8.1 and 8.4–8.5 with these measurements once you have them.

---

## 9. Recommendation: a tiered setup

| Task | Suggested model | Why |
|---|---|---|
| Development runs (dev split, debugging arcs) | Local controller, or Haiku 5.5 / GPT-6 Luna | Many runs; near-zero cost |
| Judge scoring | Local model or Haiku 5.5, a **different** model from the controller | High volume, simple rubric |
| Noise-mail classification | Local or the cheapest Copilot model | Very high volume |
| Validation runs | Sonnet 5.5 or Opus 5.5 | Fewer runs; quality matters |
| Sealed / final claims | The model you would actually deploy | The result must reflect production |
| Writer (LoRA) and CLM encoder | Local vLLM | Required; Copilot cannot serve your adapters |

Switch a profile's model with `hermes -p <profile> model` (or edit its `config.yaml`), and
record the model in the run label so scores stay comparable.

---

## 10. Caveats

- Token counts were measured on Opus 5.5. Other models tokenise differently, and reasoning
  models can produce several times more output tokens, which is billed as output.
- Cheaper models may fail more tool calls; a failed job still costs tokens. See the
  "no `tool_calls`" and `no_draft` rows in [DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md).
- Promotional prices (Gemini) expire; all prices change over time.
- Local hardware price, speed and electricity figures are estimates, not measurements on
  this project's machines.
- The cache read/write split is assumed (section 4).

---

## 11. Next step: a cheap model bake-off

Before choosing, measure quality and cost together on today's 9 scenarios:

1. For each candidate model, set it on the profiles and run the 9 scenarios with a label such
   as `bake-<model>:<fixture>` (see the hill-climbing loop in
   [SIMULATED_CORP_GUIDE.md](./SIMULATED_CORP_GUIDE.md#5-the-hill-climbing-loop)).
2. Record pass rate, safety failures, failed jobs and `hermes insights` tokens per model.
3. Cost: about $0.02 (Haiku 5.5) to $1 (Opus 5.5) per model on Copilot; about free locally.
4. Pick the cheapest model per tier in section 9 that keeps safety failures at zero.
