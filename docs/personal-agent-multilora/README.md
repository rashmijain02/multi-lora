# PersonaDesk workshop

Documentation: `docs/personal-agent-multilora/`. Code and workshop-relative commands: `workshops/personal-agent-multilora/`.

PersonaDesk runs per-persona email assistants on **Hermes Agent**. Three parts each have a narrow
job:

| Part | Responsibility | Not allowed |
|------|----------------|-------------|
| **Controller** (Hermes profile + model) | Reads the message, looks up policy, runs checks, requests a draft | Sending, approving, paying, editing memory or skills unreviewed |
| **Writer** (base model + persona LoRA adapter) | Phrases the reply in the persona's voice from verified facts | Tools, memory, or approvals |
| **Human reviewer** (listed OS operator) | Approves or rejects the exact draft revision; consents to learning | — |

New learners: start with the step-by-step [docs/USER_GUIDE.md](USER_GUIDE.md), then build
the simulated company with [docs/SIMULATED_CORP_GUIDE.md](SIMULATED_CORP_GUIDE.md).
Where the stories go next: [docs/STORY_PLAN_ENTERPRISE.md](STORY_PLAN_ENTERPRISE.md)
(company-wide arcs) and three legal arcs:
[change of control](STORY_PLAN_LEGAL_CHANGE_OF_CONTROL.md),
[MSA negotiation](STORY_PLAN_LEGAL_MSA_NEGOTIATION.md),
[litigation hold](STORY_PLAN_LEGAL_LITIGATION_HOLD.md).
Design: [PROPOSAL.md](PROPOSAL.md). Phased learning path: [LEARNING_PLAN.md](LEARNING_PLAN.md).
Full GPU experience: [docs/DGX_SPARK_GUIDE.md](DGX_SPARK_GUIDE.md).
Model costs (Copilot vs DGX Spark): [docs/COST_MODEL.md](COST_MODEL.md).

## Layout

| Path | Contents |
|------|----------|
| `hermes_plugin/` | The `personadesk` Hermes plugin (tools, hook, job store, CLI, releases, classifier) |
| `config/persona_permissions.json` | Per-persona grants: Hermes profile, tasks, tools, policies, checks, blocked actions |
| `config/operators.example.json` | Template for `config/operators.json` (ignored by Git): who may review which persona |
| `fixtures/<persona>/` | Synthetic inbound messages; `expected` fields are hidden from the model |
| `policies/<persona>/` | Versioned policy documents with front matter |
| `profiles/pd-*/SOUL.md` | Controller identity per Hermes profile |
| `scripts/setup_hermes.py` | Wires the plugin and persona profiles into a Hermes home (plan mode by default) |
| `scripts/fake_hermes.py` | Stand-in Hermes worker for E0 (no model) |
| `scripts/writer_service.py` | Loopback writer service (PEFT or vLLM Multi-LoRA backend) |
| `scripts/classification_k0.py` | K0 lexical C10 baseline exported as JSON |
| `mailsim/`, `config/mailboxes.json` | Local-only SMTP/IMAP mail simulator, optional JMAP-subset playground (`jmap*.py`), and the closed account list (`pd-mail`) |
| `tests/` | Offline test suite (no GPU, no network) |
| `artifacts/` | Runtime state, feedback, releases, and classifier outputs (ignored by Git) |

## Plugin surface

| Hermes construct | PersonaDesk use |
|------------------|-----------------|
| Tools | `pd_read_fixture`, `pd_get_policy`, `pd_run_check`, `pd_draft_reply`, `pd_classify_message`; plus seven `mail_*` tools only when `mail_url` is set |
| Hook | `pre_tool_call` blocks any tool outside the active profile's grant |
| Profiles | One isolated profile per persona (`pd-priya`, `pd-daniel`, `pd-noah`) |
| Settings | `plugins.entries.personadesk.settings.*` (`workshop_root`, `writer_backend`, `writer_url`, `classifier`, `mail_url`) |
| Governance | `memory.write_approval` and `skills.write_approval` on; curator and background review off |
| Worker | `hermes -p <profile> chat --oneshot` run as a bounded job by the `personadesk` CLI |

The persona is always derived from the active Hermes profile, never from a tool argument.

## Quickstart (CPU, no model)

Start in this directory (`workshops/personal-agent-multilora`):

```bash
uv sync --extra dev --extra classification
uv run pytest -q
uv run ruff check .
```

Create the operator allowlist. Copy the template and replace `your-os-username` with your OS
account name:

```bash
cp config/operators.example.json config/operators.json
```

Run one job end to end with the fake worker, then review it:

```bash
uv run personadesk --profile pd-priya --hermes-bin scripts/fake_hermes.py run --fixture priya-001
uv run personadesk --profile pd-priya show <job-id>
uv run personadesk --profile pd-priya review <job-id> --draft-hash <hash> --decision approve
```

Other commands: `status`, `retry`, `reconcile`, `export-feedback`, `intake` (see
[Local mail simulation](#local-mail-simulation)), and `release list|active|promote|rollback`.
Run `uv run personadesk --help` for the full list.

## Wiring a real Hermes install

Validate the plugin, then review the setup plan before applying it:

```bash
hermes plugins validate hermes_plugin
PERSONADESK_ROOT="$PWD" hermes plugins doctor hermes_plugin
uv run python scripts/setup_hermes.py                       # prints the plan only
uv run python scripts/setup_hermes.py --apply \
  --model <model-id> --base-url http://127.0.0.1:8000/v1    # local OpenAI-compatible controller
uv run python scripts/setup_hermes.py --apply \
  --provider copilot --model claude-opus-5.5                # or a provider Hermes already authenticates
```

`doctor` copies the plugin to a temporary home, so it needs `PERSONADESK_ROOT` to find the
workshop. On Windows PowerShell, set `$env:PERSONADESK_ROOT = (Get-Location).Path` first.

`setup_hermes.py`:
- creates each enabled persona profile with `--no-skills`;
- links the plugin into that profile's own `plugins/personadesk` folder (a junction on Windows, a
  symlink elsewhere), because each Hermes profile discovers plugins only in its own home;
- sets the governance keys and installs `SOUL.md`;
- enables the plugin.

It never clones the default profile and never edits existing secrets. Without `--model`, set the
controller per profile with `hermes -p pd-priya model`.

Then run a real job by omitting `--hermes-bin`:

```bash
uv run personadesk --profile pd-priya run --fixture priya-001
```

Hermes runs sessions inside its gateway process, so the worker's environment never reaches the
plugin. Each job is bound by a one-time token in the worker's query; only its digest is stored, in
`artifacts/locks/active-job.json`, and only while the job runs.

The gateway also keeps plugin modules loaded. After changing `hermes_plugin/` code, stop the
`hermes_cli.main ... gateway run` process and start it again with `hermes gateway ensure`;
`hermes gateway restart` can reload profiles without reimporting the plugin.

## Local mail simulation

`pd-mail` runs a small SMTP + IMAP server on loopback, written with the Python standard library
(no Docker). Only the addresses in `config/mailboxes.json` exist, and they can only email each
other: any other recipient is refused, so nothing leaves the machine. All accounts share the
documented lab password in that file.

Start in this directory and keep the server running in its own terminal:

```bash
uv run pd-mail serve                       # SMTP 127.0.0.1:2525, IMAP 127.0.0.1:1143
```

In a second terminal:

```bash
uv run pd-mail accounts                    # addresses, ports, lab password
uv run pd-mail seed --persona priya-raman-support   # send Priya's fixtures as real mail
uv run pd-mail send --from maya.chen@company.example --to priya.raman@company.example \
  --subject "Customer escalation?" --body "Anything I should know about Contoso?"
uv run pd-mail inbox --user priya.raman@company.example [--unseen]
uv run pd-mail read --user priya.raman@company.example 1 [--peek]
uv run pd-mail reset                       # empty every mailbox
```

Any IMAP/SMTP client works too: plaintext, the ports above, the account address as user name.
`uv run python scripts/setup_thunderbird.py --apply` creates a separate Thunderbird profile with
every account (the new Outlook for Windows cannot reach loopback servers); see
[docs/SIMULATED_CORP_GUIDE.md](SIMULATED_CORP_GUIDE.md).

### Mail intake (recommended path)

`intake` reads unseen mail from the active persona's own mailbox and turns each message into a
job. Drafts still wait for `review`; nothing is sent.

```bash
uv run personadesk --profile pd-priya intake          # create queued jobs
uv run personadesk --profile pd-priya intake --run    # create and run them
```

- Each message becomes a `mail-*` fixture under `artifacts/inbox/<persona>/` with
  `split: "mail"`, so it is never exported as training feedback.
- Jobs are keyed by `Message-ID`, so repeating intake never duplicates work.
- The server stamps `Authentication-Results: mailsim.personadesk.test; dmarc=pass` only when the
  SMTP login matches `From:`, and strips any sender-written copy. Intake rejects unauthenticated
  mail.
- Seeded mail carries `X-PersonaDesk-Fixture`. Intake copies that fixture's facts and clock only
  when the sender matches the fixture; other mail gets the sender's facts from
  `config/mailboxes.json`, and checks without the facts they need report `not_applicable`.

### Optional: Hermes email gateway sandbox

Hermes has a built-in email platform that polls IMAP and replies by SMTP automatically.
Automatic replies bypass PersonaDesk review, so use it only with a separate sandbox profile and
the `assistant@company.example` account, never with a `pd-*` persona profile. Put these values in
that sandbox profile's `.env`:

```text
EMAIL_ADDRESS=assistant@company.example
EMAIL_PASSWORD=<shared lab password from config/mailboxes.json>
EMAIL_IMAP_HOST=127.0.0.1
EMAIL_IMAP_PORT=1143
EMAIL_IMAP_SECURITY=plain
EMAIL_SMTP_HOST=127.0.0.1
EMAIL_SMTP_PORT=2525
EMAIL_SMTP_SECURITY=plain
EMAIL_AUTHSERV_ID=mailsim.personadesk.test
EMAIL_ALLOWED_USERS=maya.chen@company.example
```

Then send it mail with `pd-mail send --to assistant@company.example ...` and read the reply with
`pd-mail inbox --user maya.chen@company.example`.

### Optional: JMAP mailbox playground (folders, tags, drafts)

`pd-mail jmap-*` adds a second loopback server that speaks a **subset of JMAP** (RFC 8620/8621)
over the same six accounts, with a deterministic 30-message pack per persona: threads, tags,
unread state, attachments, a non-ASCII message, same-subject and dangling-reference traps, and a
prompt-injection message. It is built with the standard library and SQLite because Docker Linux
containers are not available on every workshop machine. It qualifies the tool design, not
Stalwart: nothing here has been run against a real Stalwart release (see
[EMAIL_PLAYGROUND_PROPOSAL.md](EMAIL_PLAYGROUND_PROPOSAL.md)). It does not implement
`EmailSubmission`, so nothing can be sent.

```bash
uv run pd-mail jmap-serve                  # JMAP on 127.0.0.1:8088 (config/mailboxes.json: jmap_port)
uv run pd-mail jmap-seed                   # import every pack; safe to repeat, never duplicates
uv run pd-mail jmap-seed --manifest        # print the fixture manifest and exit (no server needed)
uv run pd-mail jmap-reset                  # empty the JMAP store (artifacts/mail/jmap.db)
```

For an isolated database, put the global `--db` option before `jmap-serve` or
`jmap-reset`, using the same path for both. With no override, these commands use
`artifacts/mail/jmap.db`, not the SMTP/IMAP store.

Seeding verifies each message by `Message-ID` and content hash, so an interrupted import resumes
and changed content under a known ID is reported rather than duplicated.

To give a persona the mail tools, set the plugin's `mail_url` setting (loopback hosts only) to
`http://127.0.0.1:8088`, for example with
`uv run python scripts/setup_hermes.py --mail-url http://127.0.0.1:8088 --apply`, then restart
the Hermes gateway (see above): a running gateway keeps the old plugin and settings loaded.
Without `mail_url` the seven tools are not registered, and the rest of the workshop is unchanged.

| Tool | Effect |
|---|---|
| `mail_search`, `mail_get`, `mail_get_thread` | Read only; bounded pages; message text is flagged `untrusted_content` |
| `mail_update_tags` | Add or remove `needs-review`, `follow-up`, `waiting-on-customer` only |
| `mail_set_read`, `mail_move` | `$seen` only; move between inbox, archive, and trash |
| `mail_save_draft` | Projects the job's stored ledger draft into Drafts, unsent; idempotent per artifact hash |

The account comes from the Hermes profile and `config/mailboxes.json`, never from tool arguments.
Writes are limited to fixture messages, a stale `if_state` returns `stale_state`, partial failures
are reported per message, and every call is logged without bodies or credentials to
`artifacts/mail/audit.jsonl`. Tests: `uv run pytest tests/test_jmap.py tests/test_mail_tools.py`.
Concurrent state checks and updates are serialized within the server. Draft-save
retries reconcile obsolete projections after interrupted replacement; cleanup failures
are reported rather than silently treated as success.

[EMAIL_PLAYGROUND_PROPOSAL.md](EMAIL_PLAYGROUND_PROPOSAL.md) describes the Stalwart variant this
subset stands in for.

## Writer backends

| `writer_backend` | Use |
|------------------|-----|
| `template` | Deterministic, no GPU: wiring and policy labs |
| `http` | `scripts/writer_service.py` on `127.0.0.1:8100`, backed by PEFT (one adapter resident) or vLLM Multi-LoRA |

See the script's docstring for the PEFT command and the Spark guide for vLLM.

## Classification

The `classifier.backend` setting takes one of three values:

| Value | Behaviour |
|-------|-----------|
| `none` | Default: the tool is off |
| `lexical` | Uses the K0 JSON artifact |
| `clm` | Uses a real `clm-serve` |

A mock CLM server is refused unless `allow_mock` is set, and its results are flagged
`real_backend: false`. The CLM source is the `external/CLM` Git submodule.
