# PersonaDesk user guide: from a fresh machine to your first reviewed draft

This guide is for new learners. Follow the phases in order; each one builds on the last.
Commands use repository-relative paths, so clone the repository wherever you like.

## Phase 0: The moving parts (5 minutes)

| Part | What it is |
|------|------------|
| **Hermes Agent** | The agent framework. Each persona has its own isolated Hermes **profile**: `pd-priya`, `pd-daniel`, `pd-noah`. |
| **PersonaDesk plugin** (`hermes_plugin/`) | Adds tools to Hermes (read a message, fetch a policy, run a check, write a draft). A hook blocks anything outside the persona's grant. |
| **`personadesk` CLI** | How you run jobs, inspect drafts, and approve or reject them. The model can never approve its own work. |
| **`pd-mail`** | A local-only mail server. Only the addresses in `config/mailboxes.json` exist, and mail never leaves your machine. |
| **Writer** | Turns verified facts into reply text: `template` (no GPU) first, persona LoRA adapters later. |

The flow: **mail arrives → `intake` creates a job → Hermes drafts → you review → nothing is
ever sent.**

## Phase 1: Install prerequisites

1. **Git**: check with `git --version`.
2. **uv** (Python package manager), from <https://docs.astral.sh/uv/>: check with
   `uv --version`. uv installs Python 3.11 or newer for you.
3. **Hermes Agent**: install it from its official instructions, then check with
   `hermes --version`.
4. **A model provider Hermes can use**: either a hosted provider you are already signed in to
   (for example `copilot` with `claude-opus-5.5`), or a local OpenAI-compatible server such as
   vLLM (see [DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md)).

On Windows, open a new PowerShell window after installing so the updated `PATH` takes effect.

## Phase 2: Get the code

```bash
git clone --recurse-submodules https://github.com/rashmijain02/multi-lora.git
cd multi-lora/workshops/personal-agent-multilora
```

Every command below starts in `workshops/personal-agent-multilora`.

## Phase 3: Offline check (no model, no GPU)

1. Install dependencies and run the checks:

   ```bash
   uv sync --extra dev --extra classification
   uv run pytest -q          # every test should pass
   uv run ruff check .       # expect: All checks passed!
   ```

2. Allow yourself to review drafts:

   ```bash
   cp config/operators.example.json config/operators.json
   ```

   Edit `config/operators.json` and replace `your-os-username` with the output of `whoami`
   (on Windows, only the part after the backslash).

3. Run one job with the fake worker:

   ```bash
   uv run personadesk --profile pd-priya --hermes-bin scripts/fake_hermes.py run --fixture priya-001
   ```

   Note the `job_id` and the draft's `artifact_hash` in the output.

4. Review it:

   ```bash
   uv run personadesk --profile pd-priya show <job-id>
   uv run personadesk --profile pd-priya review <job-id> --draft-hash <hash> --decision approve
   ```

You have now seen the whole job lifecycle: `queued → running → awaiting_review → approved`.

## Phase 4: Connect real Hermes

1. Validate the plugin:

   ```bash
   hermes plugins validate hermes_plugin
   ```

2. Preview the setup plan, then apply it:

   ```bash
   uv run python scripts/setup_hermes.py                    # prints the plan only
   uv run python scripts/setup_hermes.py --apply --provider copilot --model claude-opus-5.5
   ```

   This creates the persona profiles, links the plugin into each profile, enables it, and turns
   on the governance settings.

3. Start the Hermes gateway with `hermes gateway ensure`. Hermes runs plugin tools inside this
   long-lived process. **After changing anything in `hermes_plugin/`**, stop the
   `hermes_cli.main ... gateway run` process completely and run `hermes gateway ensure` again;
   `hermes gateway restart` does not reimport plugin code.

4. Run a real job:

   ```bash
   uv run personadesk --profile pd-priya run --fixture priya-001
   uv run personadesk --profile pd-priya show <job-id>
   ```

## Phase 5: Local email

1. **Terminal 1**: start the mail server and leave it running.

   ```bash
   uv run pd-mail serve        # SMTP 127.0.0.1:2525, IMAP 127.0.0.1:1143
   ```

2. **Terminal 2**: explore and send mail.

   ```bash
   uv run pd-mail accounts                                # addresses, ports, lab password
   uv run pd-mail seed --persona priya-raman-support      # Priya's fixtures as real mail
   uv run pd-mail send --from maya.chen@company.example \
     --to priya.raman@company.example --subject "Hi" --body "Any customer issues?"
   uv run pd-mail inbox --user priya.raman@company.example
   uv run pd-mail read  --user priya.raman@company.example 1 --peek
   ```

3. Turn the inbox into jobs and draft replies:

   ```bash
   uv run personadesk --profile pd-priya intake --run
   uv run personadesk --profile pd-priya status
   uv run personadesk --profile pd-priya show <job-id>
   ```

4. Review the drafts as in Phase 3. `uv run pd-mail reset` empties every mailbox.

Experiments to try:
- Mail Daniel, then run `intake` as `pd-priya`: Priya never sees Daniel's mail.
- Run `intake` twice: no duplicate jobs are created.
- Send to `x@gmail.com`: the server refuses it.

More detail, including the optional Hermes email-gateway sandbox, is in the workshop
[README](../README.md#local-mail-simulation).

## Phase 6: Go further

- A whole simulated company with Thunderbird, stories and hill climbing:
  [SIMULATED_CORP_GUIDE.md](./SIMULATED_CORP_GUIDE.md).
- GPU writer adapters, vLLM, and CLM classification: [DGX_SPARK_GUIDE.md](./DGX_SPARK_GUIDE.md),
  sections 5 to 7.
- Self-improvement with `export-feedback` and `release promote|rollback`: guide section 8.
- Concepts phase by phase: [LEARNING_PLAN.md](../LEARNING_PLAN.md).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `uv` or `hermes` not found | Open a new terminal, or add their install folders to `PATH`. |
| `PermissionDenied` naming the operator | Your username is missing from `config/operators.json`. |
| Job `failed`: "fixture not found" or old behavior | The gateway runs stale plugin code. Stop its process, run `hermes gateway ensure`, then `personadesk --profile <p> retry <job-id>`. |
| Job `failed`: turn limit reached | Use a stronger controller model, or raise `max_turns` in `config/persona_permissions.json`. |
| `pd-mail` reports `ConnectionRefusedError` | `pd-mail serve` is not running in another terminal. |
| `hermes plugins doctor` cannot find the workshop | Set `PERSONADESK_ROOT` to this folder first. |
