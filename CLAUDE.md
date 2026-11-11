# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

An artifact-driven study of multi-LoRA serving (vLLM and others), NVIDIA NIM/Nemotron compatibility, and Azure deployment. It is mostly **documentation, notebooks, and independent workshop projects**, not one application. There is no root-level build, lint, or test command; each workshop has its own toolchain.

Read `AGENTS.md` and `_agent/rules/repository-relative-paths.mdc` before editing anything. The key rules:

- Use repository-relative paths everywhere (code, config, notebooks, docs). Never embed a drive letter, username, checkout directory, or WSL mount. State when a command starts in a subdirectory, and start setup examples from the repository root.
- Where independence from the working directory is needed, resolve paths at runtime from the source file (`Path(__file__).resolve().parents[n]`), not with hardcoded absolutes.
- Container-internal paths, API routes, and URLs are not checkout paths and keep their required syntax.
- Clear saved notebook outputs before publishing.
- Keep workshop documentation under `docs/<workshop-id>/`, one folder per workshop.
  Code, notebooks, configuration, and runtime persona/policy inputs remain under `workshops/`.

## Layout

- `curriculum/`: the 10-day study kit (`day-NN-*/README.md`), `templates/` (claim register, decision matrix, ADR, and similar), `sources/` (official-doc catalog), `papers/` (PDFs with SHA-256 checksums). `docs/multi-lora-learning-plan.md` is the master plan.
- `docs/<workshop-id>/`: each workshop's README, proposals, plans, guides, presentations,
  and evidence. The AutoResearch instruction template also lives here; its harness
  copies a rendered version into the training checkout.
- `workshops/`: six hands-on projects, in learning-path order (root `README.md` has the stage table):
  1. `email-multilora`: train and compare classification and persona-reply LoRA adapters (notebooks + `email_workshop` package, Azure/Foundry scripts in `scripts/` and `infra/`).
  2. `personal-agent-multilora`: PersonaDesk persona agents on Hermes Agent (`hermes_plugin/`, `mailsim/`, `policies/`, `profiles/`, `fixtures/`).
  3. `slm-task-models`: small LoRA student replacing the hosted router, behind a hash-locked parity gate (`slm_router`, `gates.json`).
  4. `autoresearch-spark`: Hermes-driven guarded training experiments (`harness/`, the agent may edit only `train.py`).
  5. `persona-portal`: per-persona read-only Workbench for Hermes WebUI (`sidecar/`, `ux/<persona-id>.json`).
  6. `agent-evals-vally`: Microsoft Vally eval specs (Node) for PersonaDesk (`evals/`, `graders/`, `hidden/`, `vally-hermes-executor/`).
- `ux-workspace/`: the **Workshop Hub**. Launches the Hermes WebUI fork plus a read-only hub sidecar (`hub/hub_sidecar.py`, `127.0.0.1:8766`) that discovers workshops by reading `workshops/*/workshop.json` on every request. `PLAN.md` defines the manifest contract.
- `external/`: git submodules of the user's forks: `CLM` (branch `learning`), `hermes-agent` (`main`), `hermes-webui` (`multilora-ux`). Both `hermes-*` are shallow. Treat them as upstream code; commit and push inside the submodule, then update the pointer here.

## Cross-cutting things worth knowing

- **Workshops are independent Python projects**, each with its own `pyproject.toml` and `uv.lock` (Python 3.11+, ruff line length 100 where configured). A workshop's environment is not shared, with deliberate exceptions: `persona-portal` tests run under Workshop 2's venv (`workshops/personal-agent-multilora/.venv`; the `ux-workspace` unit tests work there too), and `agent-evals-vally` drives the PersonaDesk CLI from Workshop 2 with a fake Hermes (`scripts/fake_hermes.py`).
- **Adding or changing a workshop's hub entry**: edit `workshops/<dir>/workshop.json` (schema 1; `id` must equal the folder name, `docs` paths are relative to `docs/<dir>/`, must exist and be `.md`, `builds_on` ids must exist, `commands[].cwd` and `readiness[].path` are relative to the repo root). Validate with `python ux-workspace/hub/hub_sidecar.py --check`. The hub serves only declared docs.
- **Fake vs real Hermes**: most tests and evals run against `fake_hermes.py` on a CPU. Real runs need a Hermes Agent install and a hosted or local model.
- **"Agent never grades itself"**: graders, gates, and answer keys are hash-locked or hidden (`gates.json`, `hidden/`, the AutoResearch harness metric). Do not weaken or edit these to make a run pass.
- **Never "send" anything**: PersonaDesk drafts are human-reviewed. Mail simulation uses `mailsim` (CLI `pd-mail`), a small in-repo SMTP + IMAP server written with asyncio (`mailsim/smtp.py`, `imap.py`, `store.py`), local accounts only, on SMTP 127.0.0.1:2525 and IMAP 127.0.0.1:1143. It implements the IMAP subset Python `imaplib` and Hermes' email gateway need; Thunderbird is the optional GUI client. A second, optional server speaks a JMAP subset on 127.0.0.1:8088 (`pd-mail jmap-serve|jmap-seed|jmap-reset`; `mailsim/jmap*.py`) and backs seven `mail_*` Hermes tools (`hermes_plugin/mail_tools.py`, registered only when the plugin setting `mail_url` is set; tests in `tests/test_jmap.py`, `tests/test_mail_tools.py`). It stands in for Stalwart (`EMAIL_PLAYGROUND_PROPOSAL.md`), which has not been run: Docker Linux containers are unavailable on this host. Only fixture-domain (`@mailbox.personadesk.test`) messages are writable by the tools, so server-generated Message-IDs use a different domain.
- Local-only data is git-ignored (`.gitignore`): email workshop `data/` and `artifacts/`, AutoResearch `upstream/` and `runs/`, SLM `runs/`, Workshop 2 `artifacts/` and some `config/` files, `.env*`, `.venv/`.
- Evidence discipline (curriculum): label claims Confirmed / Observed / Implementation-specific / Version-dependent / Inferred / Unverified / Contradicted, with source, access date, and version. Keep distinct: runtime LoRA support vs model-profile support vs NIM multi-LoRA vs Foundry native adapter deployment, and managed endpoint vs serverless pay-per-token.

## Commands (run from the repository root unless noted)

Python workshops use `uv`. Single test: `uv run pytest tests/test_file.py::test_name -q` from inside the workshop folder.

```powershell
# Workshop 1 (email-multilora): venv-based; see its README for setup (scripts/setup-local.ps1)
Set-Location workshops/email-multilora
.\.venv\Scripts\python.exe -m ruff check email_workshop tests scripts
.\.venv\Scripts\python.exe -m pytest tests -q          # marker "training" needs the optional training extras

# Workshop 2 (personal-agent-multilora)
Set-Location workshops/personal-agent-multilora
uv sync --extra dev --extra classification
uv run pytest -q ; uv run ruff check .
uv run personadesk --profile pd-priya --hermes-bin scripts/fake_hermes.py run --fixture priya-001

# Workshop 3 (slm-task-models) and Workshop 4 (autoresearch-spark)
uv sync ; uv run pytest -q ; uv run ruff check .        # slm: add --group train for GPU training
uv run --group dev pytest -q ; uv run --group dev ruff check .   # autoresearch (run in its folder)

# Workshop 5 (persona-portal): uses Workshop 2's venv
workshops\personal-agent-multilora\.venv\Scripts\python.exe -m pytest workshops/persona-portal/tests -q

# Workshop 6 (agent-evals-vally): Node >= 22.14, Vally pinned at 0.20.0
Set-Location workshops/agent-evals-vally
npm install ; npm test ; npm run lint:evals
node --test vally-hermes-executor/tests/<file>.test.js   # single test file
npm run eval:hello       # also eval:fake, eval:priya|daniel|noah, eval:safety, eval:safety:control

# UX workspace
python -m pytest ux-workspace/tests -q
python ux-workspace/hub/hub_sidecar.py --check           # validate every workshop.json
python ux-workspace/scripts/start_workspace.py --setup   # once; then --grant-consent to run (127.0.0.1:8787)
python ux-workspace/scripts/smoke_hub.py --webui-python ux-workspace/.venv/Scripts/python.exe
```

Notes: always go through `npm run` in Workshop 6 (the scripts disable Vally telemetry). Hub, sidecars, and the proxy bind to loopback only; keep it that way. Windows is the primary host (PowerShell); POSIX equivalents use `.venv/bin/python`.
