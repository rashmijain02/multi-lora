# UX workspace

One Hermes WebUI for every workshop. Open WebUI, click **Workshops** (top right), and the
**Workshop Hub** lists every workshop in learning-path order. For each one it shows four tabs:

| Tab | What it shows |
|---|---|
| Overview | Summary, status, what it builds on, hardware, and a readiness list (do the files and folders it needs exist?). |
| Docs | The workshop's declared docs, rendered in the hub. Links to other declared docs open in the hub; web links open in a new tab. |
| Run | Setup, check, and run commands, each with a Copy button. The hub never runs anything. |
| Ask Hermes | Starter prompts. Clicking one puts it in the chat box; you press Send. |

The design, contract, and roadmap are in [PLAN.md](PLAN.md). Commands below start at the
repository root.

## How it fits together

```text
browser ──> Hermes WebUI (our fork, external/hermes-webui, branch multilora-ux)
              │  loads extensions/multilora-manifest.json
              │    ├── workshop-hub  (hub.js, hub.css)
              │    └── personadesk   (Workshop 5 Workbench)
              │
              └─ /api/extensions/workshop-hub/sidecar/...  (login + consent + token-v1)
                    │
                    v
              ux-workspace/hub/hub_sidecar.py on 127.0.0.1:8766 (read-only)
                    │  reads on every request
                    v
              workshops/*/workshop.json  + the docs each one declares
```

WebUI stays the only thing the browser talks to. The hub sidecar has no data of its own: it
reads the workshop manifests each time, so a new workshop appears on the next refresh.

## Start

1. Check out the fork (once). The submodule follows branch `multilora-ux`:

   ```powershell
   git submodule update --init external/hermes-webui
   ```

2. Create WebUI's Python environment in `ux-workspace/.venv` (once; uses `uv` if installed):

   ```powershell
   python ux-workspace/scripts/start_workspace.py --setup
   ```

3. Start WebUI and the hub sidecar:

   ```powershell
   python ux-workspace/scripts/start_workspace.py --grant-consent
   ```

   It prints the URL (default `http://127.0.0.1:8787/`). The WebUI password comes from
   `HERMES_WEBUI_PASSWORD`, or is generated once into `ux-workspace/.state/webui-password.txt`.
   `--grant-consent` approves WebUI's sidecar proxy for `workshop-hub`. Without it, approve it
   once in **Settings → Extensions**. Stop everything with Ctrl+C.

Options: `--port`, `--state-dir`, `--webui-python <path>`, and
`--persona <id> --personadesk-db <path>` to also start the Workshop 5 Workbench sidecar.
If one process exits, the launcher stops the others (whole process trees, because WebUI
re-executes itself under the Hermes Agent's Python). If the launcher itself is killed instead
of stopped with Ctrl+C, check that nothing is still listening on ports 8766 and 8787.

The workspace keeps WebUI state in `ux-workspace/.state/webui` (git-ignored), separate from any
other WebUI you run. Your Hermes home and agent settings are passed through unchanged. Chat
needs a Hermes Agent install that WebUI can find; the hub itself does not.

## Add a workshop

Create `workshops/<dir>/workshop.json` ([PLAN.md §4](PLAN.md#4-the-workshop-manifest-contract-workshopjson-schema-1)
has every field), then validate it:

```powershell
python ux-workspace/hub/hub_sidecar.py --check
```

It prints `ok` or the exact field that is wrong for each workshop. Refresh the hub to see it.

## Tests

Unit tests (any Python 3.11+ with pytest; the Workshop 2 venv works):

```powershell
python -m pytest ux-workspace/tests -q
```

End-to-end smoke test against a real WebUI, in a temporary state directory:

```powershell
python ux-workspace/scripts/smoke_hub.py --webui-python ux-workspace/.venv/Scripts/python.exe
```

On Linux and macOS the WebUI Python is `ux-workspace/.venv/bin/python`.

## Status (measured)

| Check | Result |
|---|---|
| `hub_sidecar.py --check` | 6 of 6 workshop manifests valid |
| Unit tests (`ux-workspace/tests`) | 31 passed |
| Smoke test (`smoke_hub.py`) | 16 of 16 checks passed: both extensions loaded from one manifest, 403 before consent, token minted, 6 workshops through the proxy, detail with readiness, declared doc served, traversal refused (404), POST refused (403), direct call without token 401, cross-site 403, `hub.js` and `hub.css` served |
| Headless browser (Edge) | Hub opens, lists 6 workshops, renders Workshop 1's README, and an in-doc link opens another declared doc in the hub; no console errors |

Not done yet: running checks from the UI, per-workshop panels, and progress tracking
(phases 2–4 in [PLAN.md §8](PLAN.md#8-phases)). Known limits are in [docs/GAPS.md](docs/GAPS.md).
