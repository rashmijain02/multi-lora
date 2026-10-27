# Plan: Build a Legal-World Simulation (Law Firm + Contracts + Legal Evals)

Companion to `enterprise-sim-plan.md`. This plan covers three datasets:

| # | Dataset | Role in your simulation | License |
|---|---------|------------------------|---------|
| 2 | **Calderwood & Harkness / Harvey LAB** | The simulated law firm: clients, matters, work product, long-horizon tasks | MIT |
| 3 | **CUAD** | Real contract text with expert clause labels, used inside matters | CC BY 4.0 (attribution required) |
| 4 | **LegalBench** | Evaluation of legal reasoning, task by task | Mixed, per task ("other") |

---

## Links

**2. Harvey LAB / Calderwood & Harkness**
- Repo: https://github.com/harveyai/harvey-labs
- Law-firm data: https://github.com/harveyai/harvey-labs/tree/main/tasks/firm-knowledge
- Tutorial: `docs/tutorial.md` in the repo (setup, task inspection, running agents, scoring)
- License: MIT (repo-wide `LICENSE` file)

**3. CUAD (Contract Understanding Atticus Dataset)**
- Hugging Face: https://huggingface.co/datasets/theatticusproject/cuad-qa
- Source repo: https://github.com/TheAtticusProject/cuad
- Homepage: https://www.atticusprojectai.org/cuad
- License: CC BY 4.0 — commercial use and modification allowed; you must credit The Atticus Project

**4. LegalBench**
- Hugging Face: https://huggingface.co/datasets/nguha/legalbench
- Paper: https://arxiv.org/abs/2308.11462
- License: "other" — each task has its own license. Check every task before use.

---

## Phase 0 — Licensing and attribution (half a day)

1. Open each `LICENSE` / dataset card yourself and confirm the terms above.
2. Add to your project's `NOTICE.md`:
   - Harvey LAB: MIT, Harvey AI copyright line, pinned commit hash
   - CUAD: "CUAD by The Atticus Project, licensed under CC BY 4.0", link to the license, and a note of any changes you made
   - LegalBench: a table of each task you use with its individual license
3. Rule: **no LegalBench task with a non-commercial license goes into anything you ship.** Keep those in a separate `evals/research-only/` folder.

## Phase 1 — Get the data (1 day)

### 2. Harvey LAB
```bash
git clone https://github.com/harveyai/harvey-labs.git
cd harvey-labs
git rev-parse HEAD   # record this hash in NOTICE.md
```
The harness ships as the `lab-core` Python package. Follow `docs/tutorial.md` for the current install command and version.

Copy `tasks/firm-knowledge/` into `data/raw/legal/firm/` (read-only from then on).

### 3. CUAD
The Hugging Face version is script-based (the viewer is disabled for that reason), so the simplest route is the source archive:
```bash
mkdir -p data/raw/legal/cuad && cd data/raw/legal/cuad
curl -L -o data.zip https://github.com/TheAtticusProject/cuad/raw/main/data.zip
unzip data.zip
```
Note: some contracts contain redactions from the original public filings; the labels reflect those redactions.

### 4. LegalBench
Download only the tasks you have cleared for licensing. Tasks load by name as configs of `nguha/legalbench`; depending on your `datasets` version, script-based loading may need `trust_remote_code=True` or a manual download of `data.tar.gz` from the repo's Files tab. Store each task under `data/raw/legal/legalbench/<task_name>/`.

## Phase 2 — Explore (2–3 days)

1. **Calderwood & Harkness**: map the firm's structure.
   - Clients (46), matters (250+), practice areas, lawyers on each matter
   - File types per matter (memos, agreements, correspondence, etc.)
   - How a task references the corpus and how ground truth is defined
2. **CUAD**: list the 41 clause categories and count contracts per contract type.
3. **LegalBench**: pick 10–20 tasks that match the firm's practice areas (contracts, M&A, corporate). Record each task's license.
4. Write a one-page "firm summary": who the firm is, its biggest clients, its practice groups.

## Phase 3 — Build the law-firm environment (1–2 weeks)

Reuse the architecture from the enterprise plan (database + vector index + MCP tools + simulated clock + snapshots), with legal-specific services:

| MCP service | Example tools | Backed by |
|---|---|---|
| Document management (DMS) | `search_matter_docs`, `read_doc`, `list_matter_files` | C&H matter files |
| Matter management | `list_clients`, `get_matter`, `matter_team` | C&H client/matter tables |
| Email | `search_mail`, `read_thread`, `reply` | Generated in Phase 5 |
| Clause library | `find_clause(category)`, `compare_clause` | CUAD |
| Docket / deadlines | `upcoming_deadlines`, `add_deadline` | Generated |
| Time & billing | `log_time`, `matter_hours` | Generated |

Legal-specific rules to build in from day one:
- **Ethical walls / access control**: each agent persona only sees matters it is staffed on. Test that agents can't read walled-off matters.
- **Privilege tags** on every document and email (`privileged`, `work_product`, `external`). Agents must not send privileged material outside the firm.
- **Conflict checks**: a `check_conflicts(party)` tool that searches all clients and adverse parties.

## Phase 4 — Connect Hermes and baseline (1 week)

1. Run Hermes (vLLM endpoint, tool calling on) against the firm-knowledge tasks using Harvey's harness. LAB uses rubric-based, all-pass grading with an LLM judge, so scores are strict.
2. Run your cleared LegalBench tasks as a separate reasoning check.
3. Run a CUAD clause-extraction check: give the agent a contract, ask it to find specific clause categories, score against labels.
4. Tag failures: missed precedent, wrong matter, wrong clause, privilege breach, hallucinated citation.

## Phase 5 — Extend the firm with your own stories

1. **Firm canon** (`canon/legal/`): start from the C&H clients and matters; add lawyers with personas (partner, senior associate, junior associate, paralegal, in-house client contact, opposing counsel).
2. **Matter arcs** (`stories/legal/`), for example:

   ```yaml
   id: matter-arc-009-change-of-control
   matter: <existing C&H matter id or new>
   period: 2026-04-01 to 2026-05-15
   cast: [partner_ma, assoc_1, client_gc, opposing_counsel]
   documents_used: [cuad:<contract_id>]      # real contract text, attributed
   beats:
     - client_gc emails asking whether the deal triggers consent rights
     - assoc_1 reviews contracts, flags change-of-control clauses
     - partner pushes back on one interpretation; thread forks
     - opposing counsel requests a waiver; deadline added to docket
   ground_truth:
     - q: "Which contracts require counterparty consent on a change of control?"
       a: computed from CUAD clause labels for the listed contracts
   ```

3. **Email layer**: C&H focuses on work product, so generate the correspondence around it — client emails, internal staffing threads, opposing-counsel exchanges, deadline reminders.

## Phase 6 — Generating legal synthetic data

Same core method as the enterprise plan (canon first, role-play threads, ground truth from records), plus legal-specific practices:

1. **Matter-centric generation.** Every generated item belongs to a client and a matter. No orphan documents.
2. **Use CUAD clauses as building blocks.** Pull real clause text by category into generated agreements, then compute ground truth from the CUAD labels. Keep attribution metadata on every derived document.
3. **Model the legal workflow, not just text**: intake → conflict check → engagement letter → research → drafts → redlines → negotiation → signing → closing checklist. Each step leaves artifacts.
4. **Realistic legal noise**: superseded drafts, redline versions, "final_v3_FINAL" files, emails attaching the wrong version, reversed positions after negotiation.
5. **Privilege and confidentiality labels** on every generated item, so you can test whether agents respect them.
6. **Fictional law only where needed.** If you invent statutes or case names for stories, mark them clearly as fictional in metadata so they never leak into real-world outputs as citations.
7. **Validation**: date order, staffing consistency (only staffed lawyers appear), deadlines before closing, no real party names, LLM-judge review for legal plausibility, plus manual review of a sample — ideally by someone with legal training.
8. **Provenance on every record**: source (`harvey`, `cuad`, `generated`), generator model, prompt version, arc ID.
9. **Hold out matters** your agents never see during tuning.

## Suggested additions to your repo layout

```
enterprise-sim/
├── data/raw/legal/
│   ├── firm/            # Calderwood & Harkness (MIT)
│   ├── cuad/            # CUAD (CC BY 4.0)
│   └── legalbench/      # cleared tasks only
├── canon/legal/         # firm canon: clients, matters, lawyers, personas
├── stories/legal/       # matter arcs with ground truth
├── mcp/legal/           # DMS, matter mgmt, clause library, docket, billing
└── evals/
    ├── lab/             # Harvey harness runs
    ├── legalbench/      # cleared tasks
    └── research-only/   # non-commercial tasks, never shipped
```

## Milestones checklist

- [ ] All three licenses confirmed; `NOTICE.md` updated with attributions and pinned versions
- [ ] LegalBench tasks selected and each task's license recorded
- [ ] C&H firm mapped: clients, matters, practice areas, file types
- [ ] Legal MCP services running, with ethical walls and privilege tags
- [ ] Hermes baseline on firm-knowledge tasks, LegalBench and CUAD checks
- [ ] Firm canon v1 and first 5 matter arcs written
- [ ] Email layer generated and validated
- [ ] Held-out matters created

> Note: this environment is for building and testing agents. Outputs from agents running on it are not legal advice.
