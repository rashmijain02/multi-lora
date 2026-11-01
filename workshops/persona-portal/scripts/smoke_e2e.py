"""End-to-end smoke test: WebUI fork + PersonaDesk extension + sidecar, all on loopback.

What it proves (each step prints PASS/FAIL):

1. WebUI loads the ``personadesk`` manifest (scripts, stylesheet, token-v1 sidecar).
2. With WebUI auth on, the sidecar proxy refuses before consent and works after it.
3. WebUI mints the token file and the sidecar accepts the injected header.
4. Through the proxy, Priya's sidecar returns Priya's jobs only, never Daniel's.
5. A direct call to the sidecar without the token is refused (401).
6. A cross-site request to the proxy is refused.

Everything runs in a fresh temporary directory (``HERMES_HOME``, WebUI state, PersonaDesk
state DB), so your real Hermes home is never touched. Run from the repository root:

    python workshops/persona-portal/scripts/smoke_e2e.py --webui-python <python-with-pyyaml-and-cryptography>

The PersonaDesk store is imported from ``workshops/personal-agent-multilora``.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from http.cookies import SimpleCookie
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSHOP = HERE.parent
REPO = WORKSHOP.parents[1]
WEBUI_DIR = REPO / "external" / "hermes-webui"
SIDECAR = WORKSHOP / "sidecar" / "personadesk_sidecar.py"
SIDECAR_PORT = 8765  # must match extensions/personadesk/manifest.json in the fork
PRIYA, DANIEL = "priya-raman-support", "daniel-okafor-cfo"

sys.path.insert(0, str(REPO / "workshops" / "personal-agent-multilora"))
from hermes_plugin.store import open_store  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""), flush=True)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def request(port, method, path, *, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    data = json.dumps(body).encode() if body is not None else None
    hdrs = dict(headers or {})
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = raw[:200]
    return resp.status, payload, resp.headers


def wait_for(port: int, path: str, seconds: float = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            status, _, _ = request(port, "GET", path)
            if status < 500:
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def seed_state(db: Path) -> dict[str, str]:
    store = open_store(db)
    ids = {}
    for client, fixture, profile in ((PRIYA, "priya-001", "pd-priya"), (DANIEL, "daniel-001", "pd-daniel")):
        job, _ = store.create_job(source_key=f"smoke:{fixture}", principal="smoke", client_id=client,
                                  profile=profile, fixture_id=fixture, task="draft_reply", release_id=None)
        store.transition(job["job_id"], "running")
        store.save_draft(job_id=job["job_id"], client_id=client, body=f"Smoke draft for {fixture}.",
                         evidence=[{"kind": "fixture", "source_id": f"fixture:{fixture}", "fixture_id": fixture}],
                         uncertainties=[], blocked_actions=["send_email"], writer={"name": "smoke"})
        store.transition(job["job_id"], "awaiting_review")
        ids[client] = job["job_id"]
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.conn.close()
    return ids


def run_checks(webui_port: int, password: str, state_dir: Path, ids: dict[str, str]) -> None:
    origin = f"http://127.0.0.1:{webui_port}"
    browser = {"Origin": origin, "Sec-Fetch-Site": "same-origin"}
    proxy = "/api/extensions/personadesk/sidecar"

    status, _, hdrs = request(webui_port, "POST", "/api/auth/login", body={"password": password})
    cookie = SimpleCookie(hdrs.get("Set-Cookie", ""))
    jar = "; ".join(f"{k}={m.value}" for k, m in cookie.items())
    check("login with WebUI password", status == 200 and bool(jar), f"HTTP {status}")
    auth = {"Cookie": jar}

    status, body, _ = request(webui_port, "GET", "/api/extensions/status", headers=auth)
    body = body if isinstance(body, dict) else {}
    sidecars = body.get("sidecars", [])
    ok = (status == 200 and "/extensions/personadesk/personadesk.js" in body.get("script_urls", [])
          and len(sidecars) == 1 and sidecars[0]["proxy"]["proxy_auth"] == "token-v1")
    check("WebUI loaded the personadesk manifest", ok,
          f"posture={sidecars[0]['proxy'].get('posture') if sidecars else None}")

    status, _, _ = request(webui_port, "GET", proxy + "/v1/queue", headers={**auth, **browser})
    check("proxy refused before consent", status in (403, 409), f"HTTP {status}")

    status, _, _ = request(webui_port, "POST", "/api/extensions/sidecar-proxy-consent",
                           headers=auth, body={"id": "personadesk", "approved": True})
    check("consent granted", status == 200, f"HTTP {status}")
    check("WebUI minted the token file", (state_dir / "sidecar-auth" / "personadesk.token").is_file())

    status, body, _ = request(webui_port, "GET", proxy + "/v1/layout", headers={**auth, **browser})
    layout = body.get("layout", {}) if isinstance(body, dict) else {}
    check("layout through proxy", status == 200 and layout.get("persona") == PRIYA, f"HTTP {status}")

    status, body, _ = request(webui_port, "GET", proxy + "/v1/queue", headers={**auth, **browser})
    jobs = {j["job_id"] for j in body.get("jobs", [])} if isinstance(body, dict) else set()
    check("queue through proxy is Priya's only", status == 200 and jobs == {ids[PRIYA]},
          f"HTTP {status}, {len(jobs)} job(s)")

    status, _, _ = request(webui_port, "GET", f"{proxy}/v1/evidence?job_id={ids[DANIEL]}",
                           headers={**auth, **browser})
    check("Daniel's job is not found via Priya's sidecar", status == 404, f"HTTP {status}")

    status, _, _ = request(webui_port, "POST", proxy + "/v1/queue", headers={**auth, **browser}, body={})
    check("write method refused", status in (403, 405), f"HTTP {status}")

    status, _, _ = request(SIDECAR_PORT, "GET", "/v1/queue")
    check("direct sidecar call without token refused", status == 401, f"HTTP {status}")

    status, _, _ = request(webui_port, "GET", proxy + "/v1/queue",
                           headers={**auth, "Origin": "http://evil.invalid", "Sec-Fetch-Site": "cross-site"})
    check("cross-site proxy request refused", status == 403, f"HTTP {status}")

    status, _, _ = request(webui_port, "GET", "/extensions/personadesk/personadesk.js", headers=auth)
    check("extension script served", status == 200, f"HTTP {status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="PersonaDesk Workbench end-to-end smoke test")
    parser.add_argument("--webui-python", default=sys.executable,
                        help="Python with WebUI's requirements (pyyaml, cryptography)")
    args = parser.parse_args()

    if not (WEBUI_DIR / "extensions" / "personadesk" / "manifest.json").is_file():
        print("The fork is not on the personadesk-portal branch (extension missing).")
        return 2
    if port_in_use(SIDECAR_PORT):
        print(f"Port {SIDECAR_PORT} is busy; stop whatever uses it and retry.")
        return 2

    procs: list[subprocess.Popen] = []
    with tempfile.TemporaryDirectory(prefix="pd-smoke-", ignore_cleanup_errors=True) as tmp_name:
        tmp = Path(tmp_name)
        state_dir, home = tmp / "webui-state", tmp / "hermes-home"
        state_dir.mkdir()
        home.mkdir()
        db = tmp / "personadesk.sqlite"
        ids = seed_state(db)
        password = secrets.token_urlsafe(16)
        webui_port = free_port()

        base_env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "PERSONADESK_"))}
        base_env.update({"HERMES_HOME": str(home), "HERMES_WEBUI_STATE_DIR": str(state_dir)})
        webui_env = dict(base_env, HERMES_WEBUI_PASSWORD=password, HERMES_WEBUI_PORT=str(webui_port),
                         HERMES_WEBUI_HOST="127.0.0.1",
                         HERMES_WEBUI_EXTENSION_DIR=str(WEBUI_DIR / "extensions"),
                         HERMES_WEBUI_EXTENSION_MANIFEST="personadesk/manifest.json")
        sidecar_env = dict(base_env, PERSONADESK_STATE_DB=str(db))
        log_path = tmp / "webui.log"
        try:
            with log_path.open("w", encoding="utf-8") as log:
                procs.append(subprocess.Popen([sys.executable, str(SIDECAR), "--persona", PRIYA],
                                              env=sidecar_env, stdout=subprocess.DEVNULL,
                                              stderr=subprocess.DEVNULL))
                procs.append(subprocess.Popen([args.webui_python, "server.py"], cwd=WEBUI_DIR,
                                              env=webui_env, stdout=log, stderr=subprocess.STDOUT))
                started = wait_for(SIDECAR_PORT, "/health", 20)
                check("sidecar started", started)
                started = wait_for(webui_port, "/health", 90) and started
                check("webui started", started, f"port {webui_port}")
                if started:
                    run_checks(webui_port, password, state_dir, ids)
        finally:
            for p in procs:
                p.terminate()
            for p in procs:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
            if not all(ok for _, ok, _ in results):
                print("\n--- webui.log (tail) ---")
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-40:]))

    passed = sum(ok for _, ok, _ in results)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
