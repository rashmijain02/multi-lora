# Workshop 5: PersonaDesk Portal — a personalised Hermes WebUI per persona

This workshop gives each PersonaDesk persona from Workshop 2 a **Workbench**: structured,
read-only panels beside Hermes WebUI's own chat, shaped around that persona's job. It is
built as an **extension on our fork of hermes-webui**, not as a fork of WebUI's core, so the
fork can keep merging upstream.

Full design: [`PLAN.md`](PLAN.md). What was checked: [`docs/VERIFY.md`](docs/VERIFY.md).
What extensions could not do: [`docs/GAPS.md`](docs/GAPS.md).

## What is built so far

| Piece | Where | What it does |
|---|---|---|
| Panel catalogue | [`ux/catalog.json`](ux/catalog.json) | The fixed set of eight Workbench panels. Three have data today (work queue, draft review, evidence); five are labelled "planned" with the phase that adds them. |
| Persona layouts | [`ux/<persona-id>.json`](ux/) | One file per persona (10): panels, default panel, style tokens (accent, density, font, contrast) and release (`mvp` for Priya, Daniel, Noah). |
| Sidecar | [`sidecar/personadesk_sidecar.py`](sidecar/personadesk_sidecar.py) | Loopback, GET-only, `token-v1` service that reads the PersonaDesk state DB **read-only** for **one** persona. |
| Extension | fork branch `personadesk-portal`, `extensions/personadesk/` in [`../../external/hermes-webui`](../../external/hermes-webui) | The Workbench drawer: it fetches the layout, renders the panels, and calls the sidecar only through WebUI's proxy. |
| Tests | [`tests/`](tests/) | Layout validation and the sidecar contract (46 tests). |
| Smoke test | [`scripts/smoke_e2e.py`](scripts/smoke_e2e.py) | Starts real WebUI + sidecar in temporary directories and checks 14 steps end to end. |

## How the pieces fit

```
Browser ──► Hermes WebUI (fork)                          one container per persona (phase 4)
              │  chat (WebUI's own)
              │  Workbench drawer  ◄── extensions/personadesk/*.js|css
              │     fetch("api/extensions/personadesk/sidecar/v1/queue")
              ▼
            WebUI sidecar proxy  — same-origin check, strips cookies/auth,
              │                    injects X-Hermes-Sidecar-Token (token-v1)
              ▼
            PersonaDesk sidecar (127.0.0.1:8765, GET only, one persona)
              │  reads ux/<persona>.json and the PersonaDesk state DB (read-only)
              ▼
            jobs / drafts written by the PersonaDesk Hermes plugin (Workshop 2)
```

Why it is shaped like this:

- **Extensions cannot add backend routes** (GAP-2), so the data comes from a sidecar. WebUI's
  fixed proxy path keeps the browser on one origin.
- **`token-v1`** means only requests that came through WebUI's proxy carry the secret. Other
  local processes calling the port directly get 401.
- **One sidecar per persona.** The browser never chooses whose data it sees (GAP-4).
- **Read-only.** There are no approve buttons. Reviews stay in the PersonaDesk review
  command, so the UI adds no path around the guard.

## Run it

All commands start at the repository root. Use the PersonaDesk venv from Workshop 2 for the
tests. WebUI needs only `pyyaml` and `cryptography`; any Python 3.11+ with those works.

1. Check out the fork at the pinned workshop commit (once). The submodule follows branch
   `personadesk-portal`:

   ```powershell
   git submodule update --init external/hermes-webui
   ```

2. Run the unit tests:

   ```powershell
   workshops\personal-agent-multilora\.venv\Scripts\python.exe -m pytest workshops/persona-portal/tests -q
   ```

3. Run the end-to-end smoke test. It uses temporary state and never touches your Hermes home:

   ```powershell
   workshops\personal-agent-multilora\.venv\Scripts\python.exe workshops/persona-portal/scripts/smoke_e2e.py --webui-python <python-with-webui-requirements>
   ```

4. Look at it in a browser (manual; not yet recorded in `docs/VERIFY.md`):
   1. Choose a temporary folder for WebUI state, and use it for **both** processes.
   2. Start the sidecar:
      `HERMES_WEBUI_STATE_DIR=<state> PERSONADESK_STATE_DB=<personadesk.sqlite> python workshops/persona-portal/sidecar/personadesk_sidecar.py --persona priya-raman-support`
   3. In `external/hermes-webui`, start WebUI with `HERMES_WEBUI_PASSWORD`, the same
      `HERMES_WEBUI_STATE_DIR`, `HERMES_WEBUI_EXTENSION_DIR=extensions` and
      `HERMES_WEBUI_EXTENSION_MANIFEST=personadesk/manifest.json`.
   4. Sign in, grant sidecar proxy consent for `personadesk` in **Settings → Extensions**, then
      click **Workbench**.

## Exercises

1. **Change a persona's look.** Edit `ux/daniel-okafor-cfo.json` (try `"density": "comfortable"`
   or another accent). Run the layout tests: what do they reject, and why?
2. **Break isolation on purpose.** Remove `WHERE j.client_id = ?` from the sidecar's
   `_awaiting` query and run the tests. Which test catches it? Put the line back.
3. **Try to sneak in a write.** Add a `do_POST` route to the sidecar. Then run the smoke test:
   which layer refuses it first (see GAP-5)? Explain why that is not a reason to keep the route.
4. **Add a panel.** Design a `timeline` route for Noah from his fixtures. Add it to the
   catalogue as `available`, and write the test first.

## Status and next steps

- **Phase 1 (layouts):** built and tested. It still needs a person to review it (the
  gate in PLAN §9).
- **Phase 2:** the extension and sidecar are built and pass the smoke test. Still open: a real
  Hermes turn in WebUI with the PersonaDesk plugin and guard loaded, a browser check, and the
  container image (with the extension directory read-only, the GAP-1 interim fix).
- **Phases 3–7 (gateway, portal, evidence, remaining personas, router panel):** not started.
- **Release gate:** Workshop 6 ([`../agent-evals-vally/`](../agent-evals-vally/)) provides the
  per-persona evals.
