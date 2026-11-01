# Workshop 5 gaps: what the extension surface could not do

Rule from [`../PLAN.md`](../PLAN.md) §2: personalise through extensions first. When an
extension cannot do something, it is listed here. Only then may it become a small, labelled
`core:` commit on the fork, written as a candidate upstream PR.

Each gap names the source we read. "Observed" means we ran it; "read" means we found it in
the fork's code or docs at the pinned commit (see [`VERIFY.md`](VERIFY.md)).

| ID | Gap | Evidence | Impact | Plan |
|---|---|---|---|---|
| GAP-1 | No operator switch disables gallery install. When `HERMES_WEBUI_EXTENSION_DIR` is set, a gallery install writes into that same directory. | Read: `api/extensions.py`, `install_extension` → `_writable_extension_root` returns the configured directory. No feature flag guards the install route. | A signed-in customer could add a third-party script that runs with their full WebUI session authority, alongside our Workbench. | First `core:` candidate: an operator flag (e.g. `HERMES_WEBUI_EXTENSION_INSTALL=0`) that makes install and uninstall return 403 and hides the gallery. Interim: mount the extension directory read-only in each container (phase 2 image). |
| GAP-2 | Extensions cannot add backend routes. | Read: `docs/EXTENSIONS.md` ("WebUI does not create arbitrary extension-owned backend routes"). | Workbench data needs a separate process. | Not a core change. Solved by the loopback sidecar plus WebUI's fixed proxy path with `token-v1`. Observed working in `scripts/smoke_e2e.py`. |
| GAP-3 | A manual manifest registers ids, sidecars and settings only inside an `extensions` array. A top-level object loads the scripts and stylesheets but silently drops the sidecar and settings. | Observed: our first manifest (a single top-level object) reported `sidecars: []`, `manifest_extensions: 0`, with no warning. Read: `_manifest_extension_entries` in `api/extensions.py`. | Easy to ship a Workbench that loads but can never reach its sidecar. | Docs-only upstream candidate: warn when a top-level manifest object declares `sidecar` or `settings_schema`. Our manifest uses the array form. |
| GAP-4 | The extension cannot learn which persona a browser session belongs to. WebUI is single-user. | Read: `docs/EXTENSIONS.md` (`register(id)` exposes only `id`, `settings`, `storage`, `events`, `messages`). | One page cannot safely show several personas. | Not a core change. One persona per container (PLAN §3): each container runs its own sidecar started with `--persona`. The browser never chooses the persona. |
| GAP-5 | The proxy's same-origin check rejects unsafe methods without a CSRF token before they reach the sidecar. | Observed: a POST through the proxy got HTTP 403 from WebUI, not 405 from the sidecar. | None for a read-only sidecar. A future write route would need the WebUI CSRF token in the extension's fetch. | Keep the sidecar GET-only (405 for every other method, unit-tested). Revisit if a write route is ever added. It would also need a guard review. |
