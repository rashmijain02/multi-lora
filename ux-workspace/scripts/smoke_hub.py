"""End-to-end smoke test: WebUI fork + Workshop Hub extension + hub sidecar, all on loopback.

It uses the same environment builders as ``start_workspace.py``, so it checks the real launch
configuration, but in a fresh temporary state directory. Run from the repository root:

    python ux-workspace/scripts/smoke_hub.py --webui-python <python-with-WebUI-requirements>

Each step prints PASS/FAIL; the exit code is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from start_workspace import (
    EXTENSION_DIR,
    HUB_PORT,
    HUB_SIDECAR,
    MANIFEST,
    REPO,
    WEBUI_DIR,
    build_sidecar_env,
    build_webui_env,
    grant_consent,
    login,
    port_in_use,
    request,
    spawn,
    stop_tree,
    wait_for,
)

PROXY = "/api/extensions/workshop-hub/sidecar"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def expected_ids() -> set[str]:
    return {p.parent.name for p in (REPO / "workshops").glob("*/workshop.json")}


def run_checks(port: int, password: str, state_dir: Path) -> None:
    browser = {"Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin"}

    cookie = login(port, password)
    check("login with WebUI password", bool(cookie))
    auth = {"Cookie": cookie}

    status, body, _ = request(port, "GET", "/api/extensions/status", headers=auth)
    body = body if isinstance(body, dict) else {}
    sidecars = {s.get("id"): s for s in body.get("sidecars", [])}
    hub = sidecars.get("workshop-hub", {})
    check("WebUI loaded the combined manifest (workshop-hub + personadesk)",
          status == 200 and set(sidecars) == {"workshop-hub", "personadesk"}
          and "/extensions/workshop-hub/hub.js" in body.get("script_urls", [])
          and "/extensions/workshop-hub/hub.css" in body.get("stylesheet_urls", [])
          and hub.get("proxy", {}).get("proxy_auth") == "token-v1",
          f"HTTP {status}, sidecars={sorted(sidecars)}")

    status, _, _ = request(port, "GET", PROXY + "/v1/workshops", headers={**auth, **browser})
    check("proxy refused before consent", status in (403, 409), f"HTTP {status}")

    status = grant_consent(port, cookie, "workshop-hub")
    check("consent granted", status == 200, f"HTTP {status}")
    check("WebUI minted the token file", (state_dir / "sidecar-auth" / "workshop-hub.token").is_file())

    status, body, _ = request(port, "GET", PROXY + "/v1/workshops", headers={**auth, **browser})
    got = {w["id"] for w in body.get("workshops", [])} if isinstance(body, dict) else set()
    errors = body.get("errors", []) if isinstance(body, dict) else ["no body"]
    check("workshop list through proxy matches workshops/*/workshop.json",
          status == 200 and got == expected_ids() and not errors,
          f"HTTP {status}, {len(got)} workshop(s), {len(errors)} error(s)")

    status, body, _ = request(port, "GET", PROXY + "/v1/workshops/persona-portal", headers={**auth, **browser})
    detail = body if isinstance(body, dict) else {}
    readiness = detail.get("readiness", [])
    check("workshop detail with readiness", status == 200 and detail.get("id") == "persona-portal"
          and bool(readiness) and all("present" in r for r in readiness), f"HTTP {status}")

    status, body, _ = request(port, "GET", PROXY + "/v1/workshops/persona-portal/doc?path=README.md",
                              headers={**auth, **browser})
    check("declared doc served", status == 200 and isinstance(body, dict) and len(body.get("markdown", "")) > 100,
          f"HTTP {status}")

    status, _, _ = request(port, "GET", PROXY + "/v1/workshops/persona-portal/doc?path=../../README.md",
                           headers={**auth, **browser})
    check("undeclared / traversal doc refused", status in (400, 404), f"HTTP {status}")

    status, _, _ = request(port, "POST", PROXY + "/v1/workshops", headers={**auth, **browser}, body={})
    check("write method refused", status in (403, 405), f"HTTP {status}")

    status, _, _ = request(HUB_PORT, "GET", "/v1/workshops")
    check("direct sidecar call without token refused", status == 401, f"HTTP {status}")

    status, _, _ = request(port, "GET", PROXY + "/v1/workshops",
                           headers={**auth, "Origin": "http://evil.invalid", "Sec-Fetch-Site": "cross-site"})
    check("cross-site proxy request refused", status == 403, f"HTTP {status}")

    for asset in ("hub.js", "hub.css"):
        status, _, _ = request(port, "GET", f"/extensions/workshop-hub/{asset}", headers=auth)
        check(f"extension asset {asset} served", status == 200, f"HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Workshop Hub end-to-end smoke test")
    parser.add_argument("--webui-python", default=sys.executable,
                        help="Python with WebUI's requirements (pyyaml, cryptography)")
    args = parser.parse_args()

    if not (EXTENSION_DIR / MANIFEST).is_file():
        print("The fork is not on the multilora-ux branch (multilora-manifest.json missing).")
        return 2
    if port_in_use(HUB_PORT):
        print(f"Port {HUB_PORT} is busy; stop whatever uses it and retry.")
        return 2

    procs: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory(prefix="hub-smoke-", ignore_cleanup_errors=True) as tmp_name:
        tmp = Path(tmp_name)
        state_dir, home = tmp / "webui-state", tmp / "hermes-home"
        state_dir.mkdir()
        home.mkdir()
        password = secrets.token_urlsafe(16)
        port = free_port()
        base = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "PERSONADESK_"))}
        base["HERMES_HOME"] = str(home)
        log_path = tmp / "webui.log"
        try:
            with log_path.open("w", encoding="utf-8") as log:
                procs.append(spawn([sys.executable, str(HUB_SIDECAR), "--port", str(HUB_PORT)],
                                              env=build_sidecar_env(base, state_dir=state_dir),
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
                procs.append(spawn([args.webui_python, "server.py"], cwd=WEBUI_DIR,
                                              env=build_webui_env(base, state_dir=state_dir,
                                                                  password=password, port=port),
                                              stdout=log, stderr=subprocess.STDOUT))
                started = wait_for(HUB_PORT, "/health", 20)
                check("hub sidecar started", started)
                started = wait_for(port, "/health", 90) and started
                check("webui started", started, f"port {port}")
                if started:
                    run_checks(port, password, state_dir)
        except Exception as exc:  # noqa: BLE001 - report any failure, then show the log
            check("unexpected error", False, repr(exc))
        finally:
            for p in procs:
                stop_tree(p)

            if not all(ok for _, ok, _ in results):
                print("\n--- webui.log (tail) ---")
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-40:]))
                print(json.dumps({"state_dir": str(state_dir)}))

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
