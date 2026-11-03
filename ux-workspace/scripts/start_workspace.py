"""Start the UX workspace: Hermes WebUI (our fork) + the Workshop Hub sidecar.

Run from the repository root:

    python ux-workspace/scripts/start_workspace.py --setup     # once: WebUI's Python environment
    python ux-workspace/scripts/start_workspace.py              # start everything

Optional:

    --grant-consent          grant sidecar proxy consent for workshop-hub through WebUI's API,
                             instead of clicking it in Settings -> Extensions
    --persona <id> --personadesk-db <path>
                             also start the Workshop 5 Workbench sidecar for one persona

What it sets up, so you do not have to:

* WebUI loads ``external/hermes-webui/extensions/multilora-manifest.json`` (Workshop Hub and
  the Workshop 5 Workbench).
* WebUI state lives in ``ux-workspace/.state/webui`` (git-ignored), separate from any other
  WebUI you run. Your Hermes home and agent settings are passed through unchanged.
* A WebUI password is required for the sidecar proxy. It comes from ``HERMES_WEBUI_PASSWORD``
  or is generated once into ``ux-workspace/.state/webui-password.txt``.
* The hub sidecar gets the same ``HERMES_WEBUI_STATE_DIR``, so it finds the token WebUI mints.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from http.cookies import SimpleCookie
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKSPACE = REPO / "ux-workspace"
WEBUI_DIR = REPO / "external" / "hermes-webui"
EXTENSION_DIR = WEBUI_DIR / "extensions"
MANIFEST = "multilora-manifest.json"
HUB_SIDECAR = WORKSPACE / "hub" / "hub_sidecar.py"
PD_SIDECAR = REPO / "workshops" / "persona-portal" / "sidecar" / "personadesk_sidecar.py"
HUB_PORT = 8766  # must match the workshop-hub origin in multilora-manifest.json
PD_PORT = 8765   # must match the personadesk origin in multilora-manifest.json
STATE_ROOT = WORKSPACE / ".state"
VENV = WORKSPACE / ".venv"


def venv_python(venv: Path = VENV) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def request(port: int, method: str, path: str, *, headers=None, body=None):
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
        payload = raw
    return resp.status, payload, resp.headers


def wait_for(port: int, path: str, seconds: float = 60) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if request(port, "GET", path)[0] < 500:
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def ensure_password(state_root: Path = STATE_ROOT) -> str:
    if os.environ.get("HERMES_WEBUI_PASSWORD"):
        return os.environ["HERMES_WEBUI_PASSWORD"]
    path = state_root / "webui-password.txt"
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        return path.read_text(encoding="utf-8").strip()
    state_root.mkdir(parents=True, exist_ok=True)
    password = secrets.token_urlsafe(18)
    path.write_text(password + "\n", encoding="utf-8")
    return password


def build_webui_env(base: dict[str, str], *, state_dir: Path, password: str,
                    host: str = "127.0.0.1", port: int = 8787) -> dict[str, str]:
    env = dict(base)
    env.update({
        "HERMES_WEBUI_STATE_DIR": str(state_dir),
        "HERMES_WEBUI_PASSWORD": password,
        "HERMES_WEBUI_HOST": host,
        "HERMES_WEBUI_PORT": str(port),
        "HERMES_WEBUI_EXTENSION_DIR": str(EXTENSION_DIR),
        "HERMES_WEBUI_EXTENSION_MANIFEST": MANIFEST,
    })
    # A manual manifest replaces these; leftovers from another setup would inject other assets.
    env.pop("HERMES_WEBUI_EXTENSION_SCRIPT_URLS", None)
    env.pop("HERMES_WEBUI_EXTENSION_STYLESHEET_URLS", None)
    return env


def build_sidecar_env(base: dict[str, str], *, state_dir: Path) -> dict[str, str]:
    env = dict(base)
    env["HERMES_WEBUI_STATE_DIR"] = str(state_dir)
    env.pop("HERMES_EXT_SIDECAR_TOKEN_FILE", None)
    return env


def login(port: int, password: str) -> str:
    status, _, hdrs = request(port, "POST", "/api/auth/login", body={"password": password})
    if status != 200:
        raise RuntimeError(f"WebUI login failed (HTTP {status})")
    cookie = SimpleCookie(hdrs.get("Set-Cookie", ""))
    return "; ".join(f"{k}={m.value}" for k, m in cookie.items())


def grant_consent(port: int, cookie: str, ext_id: str) -> int:
    status, _, _ = request(port, "POST", "/api/extensions/sidecar-proxy-consent",
                           headers={"Cookie": cookie}, body={"id": ext_id, "approved": True})
    return status


def spawn(cmd: list[str], **kwargs) -> subprocess.Popen:
    # Own process group, so stop_tree() can also reach grandchildren (WebUI re-executes itself
    # under the Hermes Agent's Python).
    if os.name == "nt":
        kwargs.setdefault("creationflags", subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs.setdefault("start_new_session", True)
    return subprocess.Popen(cmd, **kwargs)


def stop_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def setup_venv() -> int:
    requirements = WEBUI_DIR / "requirements.txt"
    if not requirements.is_file():
        print("external/hermes-webui is empty. Run: git submodule update --init external/hermes-webui")
        return 2
    uv = shutil.which("uv")
    if uv:
        steps = [[uv, "venv", str(VENV)],
                 [uv, "pip", "install", "--python", str(venv_python()), "-r", str(requirements)]]
    else:
        steps = [[sys.executable, "-m", "venv", str(VENV)],
                 [str(venv_python()), "-m", "pip", "install", "-r", str(requirements)]]
    for cmd in steps:
        print("+", " ".join(cmd))
        if subprocess.call(cmd, cwd=REPO) != 0:
            return 1
    print(f"WebUI Python ready: {venv_python().relative_to(REPO)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start Hermes WebUI with the Workshop Hub")
    parser.add_argument("--setup", action="store_true", help="create ux-workspace/.venv with WebUI's requirements and exit")
    parser.add_argument("--webui-python", default=None, help="Python with WebUI's requirements (default: ux-workspace/.venv)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("HERMES_WEBUI_PORT", "8787")))
    parser.add_argument("--state-dir", default=None, help="WebUI state directory (default: ux-workspace/.state/webui)")
    parser.add_argument("--grant-consent", action="store_true", help="grant sidecar proxy consent through WebUI's API")
    parser.add_argument("--persona", default=None, help="also start the Workshop 5 Workbench sidecar for this persona")
    parser.add_argument("--personadesk-db", default=os.environ.get("PERSONADESK_STATE_DB"),
                        help="PersonaDesk state database for --persona")
    args = parser.parse_args(argv)

    if args.setup:
        return setup_venv()

    webui_python = Path(args.webui_python) if args.webui_python else venv_python()
    if not webui_python.exists():
        print(f"No WebUI Python at {webui_python}. Run with --setup first, or pass --webui-python.")
        return 2
    if not (EXTENSION_DIR / MANIFEST).is_file():
        print("The fork is missing extensions/multilora-manifest.json. Run:\n"
              "  git submodule update --init external/hermes-webui")
        return 2
    busy = [p for p in (HUB_PORT, args.port) + ((PD_PORT,) if args.persona else ()) if port_in_use(p)]
    if busy:
        print(f"Port(s) {', '.join(map(str, busy))} already in use. Stop the other process and retry.")
        return 2
    if args.persona and not args.personadesk_db:
        print("--persona needs --personadesk-db (or PERSONADESK_STATE_DB).")
        return 2

    state_dir = Path(args.state_dir) if args.state_dir else STATE_ROOT / "webui"
    state_dir.mkdir(parents=True, exist_ok=True)
    password = ensure_password()
    base = dict(os.environ)
    sidecar_env = build_sidecar_env(base, state_dir=state_dir)

    procs: list[subprocess.Popen] = []
    try:
        procs.append(spawn([sys.executable, str(HUB_SIDECAR), "--port", str(HUB_PORT)], env=sidecar_env))
        if args.persona:
            procs.append(spawn(
                [sys.executable, str(PD_SIDECAR), "--persona", args.persona, "--port", str(PD_PORT)],
                env=dict(sidecar_env, PERSONADESK_STATE_DB=args.personadesk_db)))
        procs.append(spawn(
            [str(webui_python), "server.py"], cwd=WEBUI_DIR,
            env=build_webui_env(base, state_dir=state_dir, password=password, port=args.port)))

        if not wait_for(HUB_PORT, "/health", 20) or not wait_for(args.port, "/health", 120):
            print("WebUI or the hub sidecar did not start. See the output above.")
            return 1
        if args.grant_consent:
            cookie = login(args.port, password)
            for ext_id in ["workshop-hub"] + (["personadesk"] if args.persona else []):
                print(f"Proxy consent for {ext_id}: HTTP {grant_consent(args.port, cookie, ext_id)}")

        source = "HERMES_WEBUI_PASSWORD" if os.environ.get("HERMES_WEBUI_PASSWORD") else \
            str((STATE_ROOT / "webui-password.txt").relative_to(REPO))
        print("\nUX workspace is running.")
        print(f"  Open      http://127.0.0.1:{args.port}/  and click 'Workshops' (top right)")
        print(f"  Password  in {source}")
        if not args.grant_consent:
            print("  First run Settings -> Extensions -> allow the sidecar proxy for 'workshop-hub'")
        print("  Stop      Ctrl+C\n")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        print("A process exited; stopping the workspace.")
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            stop_tree(p)


if __name__ == "__main__":
    raise SystemExit(main())
