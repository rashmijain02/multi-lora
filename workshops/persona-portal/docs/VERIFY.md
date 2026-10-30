# Workshop 5 verification checklist

Every item below was either **observed** by running it, **read** from the fork's code or
docs, or is still **open**. All runs used fresh temporary `HERMES_HOME` and
`HERMES_WEBUI_STATE_DIR` directories, as the fork's `AGENTS.md` requires. No real Hermes home
was touched.

## Versions

| Item | Value |
|---|---|
| Fork | `rashmijain02/hermes-webui`, submodule `external/hermes-webui` |
| Fork base commit | `2ea4304` (`master`, "Merge pull request #8601 from nesquena/stage/1029-8599") |
| Workshop branch on the fork | `personadesk-portal`, commit `fcd689e` (one extension-only commit on the base; the submodule is pinned here) |
| WebUI Python deps used | `pyyaml`, `cryptography` (WebUI `requirements.txt`), in a throwaway venv outside the repo |
| Sidecar | Python 3.12 standard library only |

## Phase 0 items

| # | Item | Status | How |
|---|---|---|---|
| 1 | Extension loads via `HERMES_WEBUI_EXTENSION_DIR` + `HERMES_WEBUI_EXTENSION_MANIFEST` | ✅ observed | `get_extension_status()` and the running server's `/api/extensions/status` list `/extensions/personadesk/personadesk.js` and `.css`. The script is served with HTTP 200. |
| 2 | Subdirectory manifest resolves assets under `/extensions/<dir>/` | ✅ observed | Manifest at `personadesk/manifest.json` → `/extensions/personadesk/...` |
| 3 | Sidecar declaration accepted with `proxy_auth: token-v1` | ✅ observed | Status shows one sidecar, `proxy_auth: token-v1`, no warnings (after GAP-3 fix) |
| 4 | `token-v1` posture is `local_unprotected` without a password and `protected` with one | ✅ observed | Offline status check (no password) and smoke test (password set) |
| 5 | Proxy refuses before consent, works after consent | ✅ observed | Smoke test: 403 before consent, then 200 |
| 6 | WebUI mints `STATE_DIR/sidecar-auth/personadesk.token` on consent, and the sidecar finds it through the documented lookup order | ✅ observed | Smoke test: the token file exists and proxied requests return 200 |
| 7 | Cross-site requests to the proxy are refused | ✅ observed | Smoke test: `Sec-Fetch-Site: cross-site` → 403 |
| 8 | Settings schema accepted (`permissions.storage.owned: true`) | ✅ observed | Status lists both boolean settings |
| 9 | Gallery install can be disabled | ❌ read: no switch | GAP-1 |
| 10 | Skins via `window.registerHermesSkin` | 📖 read only | `docs/EXTENSIONS.md`. The Workbench uses scoped CSS variables instead; a per-persona skin is open. |
| 11 | PersonaDesk plugin and guard load in WebUI's in-process agent | ⏳ open | Needs a real Hermes agent behind WebUI |
| 12 | Workbench renders in a real browser | ⏳ open | `node --check` passes, but no browser run yet. Manual steps are in [`../README.md`](../README.md). |

## Automated checks (measured)

Run from the repository root.

| Command | Result |
|---|---|
| `python -m pytest workshops/persona-portal/tests -q` (PersonaDesk venv) | 46 passed |
| `python workshops/persona-portal/scripts/smoke_e2e.py --webui-python <webui-venv-python>` | 14/14 checks passed |
| `node --check external/hermes-webui/extensions/personadesk/personadesk.js` | exit 0 |

The 46 tests are 24 layout tests (one-per-persona, MVP set, per-layout validation, catalogue,
no secrets or machine paths) and 22 sidecar tests:

- loopback bind
- `/health` without a token, with CORS on `/health` only
- 401 for a missing or wrong token
- 503 for a missing token file
- token rotation
- 405 for POST, PUT, PATCH, DELETE and OPTIONS
- persona-scoped queue, drafts and evidence
- 404 for another persona's job
- the DB file is unchanged after reads
- 503 for a missing DB
- unknown persona fails fast
- the token lookup order

## Smoke test output (last run)

```
PASS  sidecar started
PASS  webui started
PASS  login with WebUI password  (HTTP 200)
PASS  WebUI loaded the personadesk manifest  (posture=protected)
PASS  proxy refused before consent  (HTTP 403)
PASS  consent granted  (HTTP 200)
PASS  WebUI minted the token file
PASS  layout through proxy  (HTTP 200)
PASS  queue through proxy is Priya's only  (HTTP 200, 1 job(s))
PASS  Daniel's job is not found via Priya's sidecar  (HTTP 404)
PASS  write method refused  (HTTP 403)
PASS  direct sidecar call without token refused  (HTTP 401)
PASS  cross-site proxy request refused  (HTTP 403)
PASS  extension script served  (HTTP 200)

14/14 checks passed
```

The "write method refused" check got 403 from WebUI's CSRF check before the request reached
the sidecar (GAP-5). The sidecar's own 405 is covered by the unit tests.
