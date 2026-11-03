# UX workspace: one Hermes WebUI for every workshop

**Status:** phase 1 built and checked: 31 unit tests and a 16-check smoke test pass against
real WebUI, and a headless-browser check passes (see [README.md](README.md#status-measured)).
Phases 2–5 are planned (see [§8](#8-phases)). Commands in this file run from the
repository root unless a step says otherwise.

## 1. Why this exists

The repository now has six workshops, and more are coming. Each one has its own README, plan,
commands, and sometimes its own UI. A learner has to open a dozen files to answer simple
questions: *Which workshop comes next? What do I need installed? How do I check it works?*

The UX workspace answers those questions in one place: **Hermes WebUI**, through our fork
[`../external/hermes-webui`](../external/hermes-webui). We use WebUI because:

- it is already the place where you chat with Hermes, so "read about a workshop" and "ask Hermes
  about it" sit side by side;
- Workshop 5 already proved its extension system, sidecar proxy, and token checks on our fork;
- the fork is a git submodule, so we can change WebUI's own UX system when an extension is not
  enough, and keep those changes reviewable.

## 2. What a learner sees

A **Workshops** button opens the **Workshop Hub**, a full-height panel over WebUI's chat:

| Area | What it shows |
|---|---|
| Left list | Every workshop in learning-path order, with its status (built, partial, planned), "optional" badge, and hardware. |
| **Overview** tab | Summary, what it builds on from earlier workshops, hardware, and a readiness check (are the docs present? is the workshop's environment installed?). |
| **Docs** tab | The workshop's own README, plan, and guides, rendered with WebUI's markdown renderer. Links to other declared docs open in the hub. |
| **Run** tab | The setup, check, and try-it commands from the workshop's README, each with its working directory and a Copy button. Phase 1 never runs them for you (see [§6](#6-security-posture)). |
| **Ask Hermes** tab | Ready-made prompts. One click puts the prompt in WebUI's chat box and closes the hub; you decide whether to send it. |

Workshop-specific UIs, such as the Workshop 5 Workbench, stay their own extensions and load in
the same WebUI.

## 3. Architecture

```text
Browser ── Hermes WebUI (fork, branch multilora-ux) ─────────────────────────────┐
   │        • injects extensions listed in extensions/multilora-manifest.json      │
   │        • workshop-hub/hub.js  → Workshop Hub panel                            │
   │        • personadesk/*        → Workshop 5 Workbench (optional)               │
   │                                                                              │
   │  fetch api/extensions/workshop-hub/sidecar/v1/...   (same origin, cookie)    │
   ▼                                                                              │
WebUI sidecar proxy ── checks login + consent, strips cookies, adds token-v1 ─────┘
   │
   ▼  http://127.0.0.1:8766  (loopback only)
Hub sidecar  ux-workspace/hub/hub_sidecar.py   (Python stdlib, GET only)
   │  discovers  workshops/*/workshop.json  and validates each one
   ▼
Repository files (read only): README.md, PLAN.md, docs/... declared by each workshop
```

Three pieces, each with one job:

1. **Workshop manifests** (`workshops/<dir>/workshop.json`). Each workshop describes itself. The
   hub has no hard-coded list, so a new workshop appears when its manifest is valid.
2. **Hub sidecar** (`ux-workspace/hub/hub_sidecar.py`). WebUI extensions cannot add backend
   routes (Workshop 5 [GAP-2](../workshops/persona-portal/docs/GAPS.md)), so a small loopback
   service reads the manifests and the declared docs and serves them as JSON.
3. **Workshop Hub extension** (`external/hermes-webui/extensions/workshop-hub/`). Plain
   JavaScript and CSS, injected by WebUI. It builds the panel with DOM APIs and only uses
   `innerHTML` for output from WebUI's own `renderMd`, which escapes raw HTML.

A launcher, `ux-workspace/scripts/start_workspace.py`, starts WebUI and the hub sidecar with
matching settings so learners do not have to set seven environment variables by hand.

## 4. The workshop manifest contract (`workshop.json`, schema 1)

Every workshop folder that wants to appear in the hub adds one file:

```json
{
  "schema": 1,
  "id": "persona-portal",
  "order": 7,
  "label": "Workshop 5",
  "title": "PersonaDesk Portal",
  "summary": "One or two sentences.",
  "status": "partial",
  "optional": true,
  "hardware": "CPU is enough for what is built so far",
  "builds_on": ["personal-agent-multilora"],
  "docs": [{"path": "README.md", "title": "Start here"}],
  "readiness": [{"label": "Layouts", "path": "workshops/persona-portal/ux/catalog.json"}],
  "commands": [
    {"kind": "check", "label": "Unit tests", "cwd": ".", "run": "uv run pytest -q"}
  ],
  "prompts": [{"label": "Explain the sidecar", "prompt": "..."}],
  "extensions": ["personadesk"]
}
```

| Field | Rule | Why |
|---|---|---|
| `schema` | Must be `1`. | Lets the format change later without breaking old readers. |
| `id` | Lower-case slug, equal to the folder name. | One id per workshop; easy to find the folder. |
| `order` | Integer; the learning-path stage from the root README. | Sorts the list. |
| `label`, `title`, `summary` | Non-empty text. `summary` at most 400 characters. | Shown in the list and overview. |
| `status` | `built`, `partial`, or `planned`. | Sets expectations honestly. |
| `optional` | Boolean. | Mirrors "(optional)" in the root README. |
| `hardware` | Text. | The first question learners ask. |
| `builds_on` | Ids of other workshops. Each must exist. | Draws the dependency line. |
| `docs` | At least one. Each `path` is relative to the workshop folder, ends in `.md`, has no `..`, and the file exists. | The hub serves **only** these files. |
| `readiness` | Optional. Each `path` is relative to the **repository root**, with no `..`. | The hub reports whether it exists (for example another workshop's environment). It never reads it. |
| `commands` | `kind` is `setup`, `check`, or `try`. `cwd` is relative to the **repository root**. `run` is copied from the workshop's README. Optional `note`. | Displayed for copying. Nothing runs them in phase 1. |
| `prompts` | Optional. `label` and `prompt` text. | Pre-fills WebUI's chat box. |
| `extensions` | Optional. WebUI extension ids that belong to this workshop. | The hub says which extra UI the workshop adds. |

An invalid manifest does not break the hub. The sidecar skips it and lists the reason under
`errors`, and the hub shows those errors at the bottom of the list so the workshop author sees
them.

## 5. Working with the fork

- The submodule [`external/hermes-webui`](../external/hermes-webui) tracks branch
  **`multilora-ux`** on [rashmijain02/hermes-webui](https://github.com/rashmijain02/hermes-webui).
  It starts from `personadesk-portal` (Workshop 5), so both extensions live on one branch.
- **Extensions first.** New UX goes in `extensions/<id>/`. A change to WebUI core (`api/`,
  `static/`) is allowed only when an extension cannot do the job. It must be its own commit,
  prefixed `core:`, written so it could go upstream as a pull request, and recorded in
  [`docs/GAPS.md`](docs/GAPS.md).
- `extensions/multilora-manifest.json` is the one manual manifest WebUI reads. It must use the
  `extensions` array form, because a top-level object silently drops sidecars and settings
  (Workshop 5 GAP-3).
- Sync upstream regularly: merge upstream `master` into `multilora-ux`, rerun the smoke test, and
  bump the submodule pointer in this repository in the same pull request.

## 6. Security posture

The hub is a reading tool. Phase 1 adds no way to change anything on disk.

| Rule | How it is enforced |
|---|---|
| Loopback only | The sidecar binds to `127.0.0.1`. |
| Only WebUI can call it | Every route except `/health` needs the token-v1 header, compared in constant time; the token file is re-read on each request. WebUI adds the header only after login and proxy consent. |
| Read only | `GET` only; every other method gets 405. |
| No arbitrary file reads | `/doc` serves a path only if it is listed in that workshop's `docs`, after resolving it and checking that it stays inside the workshop folder. Size cap 512 KB. |
| No command execution | Commands are text for copying. Running checks from the UI is phase 2, behind its own design review. |
| No HTML injection | Panel text uses `textContent`. Docs use WebUI's `renderMd`, which escapes raw HTML; without it, docs show as plain text. |
| Chat stays in the learner's hands | Prompts are only placed in the chat box; the learner presses Send. |

## 7. File layout

```text
ux-workspace/
├── PLAN.md                  this file
├── README.md                how to start and use the workspace
├── docs/GAPS.md             what the extension surface could not do (and core: changes)
├── hub/hub_sidecar.py       registry discovery + validation + read-only HTTP service
├── scripts/start_workspace.py   start WebUI + hub sidecar (+ optional Workbench sidecar)
├── scripts/smoke_hub.py     end-to-end check against real WebUI
└── tests/test_hub.py        unit tests, including "every real workshop.json is valid"

workshops/<dir>/workshop.json   one per workshop

external/hermes-webui/extensions/  (fork, branch multilora-ux)
├── multilora-manifest.json  lists workshop-hub and personadesk
└── workshop-hub/{hub.js, hub.css, README.md}
```

## 8. Phases

| Phase | Goal | Done when |
|---|---|---|
| 0. Facts | Know what WebUI extensions can do. | Done in Workshop 5 ([VERIFY.md](../workshops/persona-portal/docs/VERIFY.md)). |
| 1. Read-only hub | Manifests for all six workshops, hub sidecar, hub extension, launcher. | Unit tests pass; every real manifest validates; the smoke test passes against real WebUI (login, consent, list, detail, doc, doc allowlist, token checks, script served). |
| 2. Run checks from the UI | A "Run" button for `check` commands only, with live logs. | A design note covers: a fixed allowlist read from manifests at sidecar start (never from the request), WebUI's CSRF token for POST (Workshop 5 GAP-5), one run at a time, a timeout, and no shell. Then tests and the smoke test cover it. |
| 3. Workshop panels | Rich views per workshop: embed the Workbench, show Vally results, chart AutoResearch runs and router parity rounds. | Each panel reads only declared result files and reports only measured numbers. |
| 4. Personalisation | Per-workshop accent and a learner progress tracker stored in extension storage. | Works on mobile width; progress survives a reload. |
| 5. Upstream | Offer generic fixes back to hermes-webui. | Each `core:` commit has an upstream PR or a written reason why not. |

## 9. How to add a new workshop

1. Create `workshops/<dir>/workshop.json` following [§4](#4-the-workshop-manifest-contract-workshopjson-schema-1).
2. Copy commands from your README; do not invent new ones.
3. Run the hub tests (see [README.md](README.md)). The test "every real workshop.json is valid"
   names the field that is wrong.
4. Refresh the hub. Your workshop appears in its `order` position.

## 10. Risks and open questions

- **Chat needs a Hermes Agent install.** The hub works without one, but the Ask Hermes tab only
  fills the chat box; sending needs an Agent that WebUI can find (see the fork's README,
  "Hermes agent dir"). Workshop 2's user guide covers installing Hermes.
- **One manual manifest.** WebUI reads one `HERMES_WEBUI_EXTENSION_MANIFEST`, so every extension
  this repository uses must be listed in `multilora-manifest.json`.
- **Gallery installs** still write into the extension directory (Workshop 5 GAP-1). Do not
  install gallery extensions into the workspace.
- **Doc links.** Links to a workshop's declared docs open in the hub; other relative links are
  shown as plain text, not followed (see [GAPS.md](docs/GAPS.md) UX-2).
