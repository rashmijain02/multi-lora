# Plan: Turn EnterpriseRAG-Bench into Your Own Corporate Simulation

Goal: fork Onyx's EnterpriseRAG-Bench (MIT) into a simulated company your Hermes agents can live in — reading threaded email, Slack, tickets and docs through tools — and then grow it with your own stories and synthetic data.

---

## Phase 0 — License and setup (half a day)

1. Read the `LICENSE` file in the GitHub repo **and** the dataset card on Hugging Face. Confirm both say MIT.
2. Create a `NOTICE.md` in your project that records:
   - Source: `onyx-dot-app/EnterpriseRAG-Bench` (GitHub + Hugging Face)
   - License: MIT, with Onyx's copyright line copied verbatim
   - The exact commit / dataset revision you forked
3. Decide your model for generation and agents (e.g. an open model on vLLM) and check its license allows using outputs as training/simulation data.

## Phase 1 — Fork and download (1 day)

1. Fork the GitHub repo to your account. Read `quickstart.md` there for the official layout and generation tooling.
2. Download the data from Hugging Face. It has separate `documents` and `questions` configs; the documents set is large (on the order of 1.4 GB of Parquet), so cache it locally.

   ```python
   from datasets import load_dataset

   REV = "main"  # replace with a pinned commit hash once you've chosen one
   docs = load_dataset("onyx-dot-app/EnterpriseRAG-Bench", "documents", revision=REV)
   qs   = load_dataset("onyx-dot-app/EnterpriseRAG-Bench", "questions", revision=REV)

   docs.save_to_disk("data/raw/documents")
   qs.save_to_disk("data/raw/questions")
   ```

3. Treat `data/raw/` as **read-only**. Every change you make goes into new layers (see Phase 5).

## Phase 2 — Explore and profile (2–3 days)

1. Print the schema and a few rows per source (Gmail, Slack, Jira, Confluence, etc.). Note which fields hold thread IDs, authors, timestamps, and links between documents.
2. Count documents per source and per month to understand the company's timeline.
3. Extract the **entity backbone** into tables:
   - People (name, role, team, manager)
   - Teams / departments
   - Projects / initiatives
   - Customers and vendors
4. Rebuild email **threads**: group by thread ID or subject + participants, order by timestamp. Spot-check 20 threads by hand.
5. Write a one-page "company summary" from what you found. This becomes the first draft of your world bible (Phase 5).

## Phase 3 — Build the simulation environment (1–2 weeks)

Make the data feel like a live company that agents interact with through tools, not a pile of files.

1. **Storage**
   - Postgres or SQLite for structured records (people, threads, tickets, messages).
   - A vector index (e.g. pgvector, Qdrant) for semantic search over document text.
2. **Mock services exposed as MCP tools** — one small server per system:
   - Mail: `search_mail`, `read_thread`, `send_mail`, `reply`
   - Chat: `search_channels`, `read_channel`, `post_message`
   - Tickets: `search_tickets`, `read_ticket`, `update_ticket`
   - Docs: `search_docs`, `read_doc`
   Write actions go to a separate `sim_writes` layer so the base data never changes.
3. **Simulated clock** — a "current date" the environment controls, so agents only see documents dated before "now". This lets you replay the company's history week by week.
4. **Episodes and reset** — snapshot the database before each run and restore after, so every experiment starts from the same state.
5. **Sandbox it** — run the agent and tools in a container with no outbound internet except your model endpoint. Locally that's Docker; later, Azure Container Apps Sandboxes in a locked-down VNet.

## Phase 4 — Connect Hermes and get a baseline (1 week)

1. Point Hermes at your vLLM endpoint (with tool calling enabled) and register the MCP tools from Phase 3.
2. Run the 500 benchmark questions. Log every tool call, answer, and latency.
3. Score against the gold answers and compare with the public leaderboard for a reference point.
4. Read 30 failures by hand and tag them: retrieval miss, wrong thread, outdated info, hallucination, tool error. This tells you what to fix in the harness and what new data to generate.

## Phase 5 — Make it your own company (ongoing)

1. **World bible** (`canon/`): the single source of truth for your version of the company.
   - Org chart, personas (tone, habits, who they email), projects, timeline, products, customers.
   - Start from the entities you extracted in Phase 2, then edit, rename, and add freely.
2. **Story arcs** (`stories/`): each arc is a short YAML spec, for example:

   ```yaml
   id: arc-017-vendor-outage
   period: 2026-03-02 to 2026-03-20
   cast: [cfo, it_lead, vendor_rep, two_engineers]
   beats:
     - vendor misses SLA; it_lead emails vendor_rep
     - engineers debate a workaround in Slack
     - cfo asks for cost impact; thread forks
     - decision reversed after new data
   ground_truth:
     - q: "Who approved the workaround, and when?"
       a: "it_lead, 2026-03-11"
   ```

3. **Layering**: keep three layers and tag every record with its origin.
   - `base` — original Onyx data (MIT, attributed)
   - `generated` — your synthetic data
   - `sim_writes` — what agents did during runs

## Phase 6 — Generating more synthetic data

Recommended approach, in order of importance:

1. **Canon first, documents second.** Generate from the world bible and story specs, never from a blank prompt. Every document should reference real entities from the canon. This is what keeps 10,000 new emails consistent with each other.
2. **Role-play generation for threads.** Instead of asking one model to write a whole thread, run a small multi-agent loop: each persona is an agent with its role, tone, knowledge and inbox, and the simulated clock advances between turns. Threads come out with realistic forks, delays and misunderstandings.
3. **Compute ground truth from the records, not from the model.** After generating an arc, derive the Q&A answers from the stored records (who sent what, when). Exact answers make grading reliable.
4. **Inject realistic noise on purpose**: off-topic threads, near-duplicates, half-finished drafts, reply-all chains, conflicting statements, decisions later reversed. This is what makes agents fail in useful ways.
5. **Validate before you keep anything.**
   - Consistency checks: dates in order, people exist, roles match the org chart, no one emails before they were hired.
   - Deduplication against existing documents.
   - An LLM judge that scores realism and flags contradictions with the canon.
   - Spot-check a random 2% by hand.
6. **Track provenance** on every generated record: generator model, prompt version, seed, story arc ID, date generated.
7. **Mix models.** Using two or three different generator models reduces the "every email sounds the same" problem.
8. **Scale gradually.** Generate one arc, run your agents on it, look at failures, then generate more of what breaks them. Aim for depth before volume.
9. **Hold out a test set.** Keep some arcs your agents never see during tuning, so you measure real improvement rather than memorization.

## Suggested repo layout

```
enterprise-sim/
├── NOTICE.md            # Onyx MIT attribution + forked revision
├── data/
│   ├── raw/             # original Onyx data, read-only
│   ├── generated/       # your synthetic data
│   └── snapshots/       # DB snapshots for episode resets
├── canon/               # world bible: org chart, personas, projects, timeline
├── stories/             # story arc specs with ground truth
├── generator/           # role-play + noise + validation pipeline
├── sim/                 # DB, vector index, simulated clock
├── mcp/                 # mock mail / chat / ticket / doc servers
├── evals/               # benchmark runner, scoring, failure tags
└── agents/              # Hermes config and your custom agents
```

## Milestones checklist

- [ ] License confirmed, `NOTICE.md` written, revision pinned
- [ ] Data downloaded and profiled; threads rebuilt and spot-checked
- [ ] Entity backbone extracted; company summary written
- [ ] Mock MCP services running against the database
- [ ] Simulated clock and episode reset working
- [ ] Hermes baseline on the 500 questions, failures tagged
- [ ] World bible v1 and first 5 story arcs written
- [ ] Generator pipeline producing validated, provenance-tagged data
- [ ] Held-out test arcs created
- [ ] Environment running inside a locked-down sandbox
