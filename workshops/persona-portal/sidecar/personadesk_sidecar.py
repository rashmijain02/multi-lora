"""Read-only Workbench sidecar for the PersonaDesk WebUI extension (Workshop 5).

The hermes-webui extension cannot add backend routes, so its data comes from this small
loopback service. WebUI's same-origin proxy forwards browser requests from
``/api/extensions/personadesk/sidecar/<path>`` to it and adds the
``X-Hermes-Sidecar-Token`` header (``proxy_auth: token-v1``).

Rules this service enforces:

* Binds to 127.0.0.1 only, and only ``GET`` is allowed (405 for every other method).
* Every route except ``/health`` needs the token-v1 secret: 503 if the token file does not
  exist yet, 401 if the header is missing or wrong. The file is re-read per request so
  WebUI can rotate it.
* One sidecar serves exactly one persona. Every query filters by that persona's
  ``client_id``; a job that belongs to someone else is reported as "not found".
* The PersonaDesk state database is opened read-only, so there is no write path that could
  skip the PersonaDesk guard.

Run (from the repository root):

    python workshops/persona-portal/sidecar/personadesk_sidecar.py \
        --persona priya-raman-support --state-db <path-to-personadesk.sqlite>
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

EXTENSION_ID = "personadesk"
TOKEN_HEADER = "X-Hermes-Sidecar-Token"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
PERSONA_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
JOB_ID_RE = re.compile(r"^job-[0-9a-f]{12}$")
DEFAULT_PORT = 8765
UX_DIR = Path(__file__).resolve().parent.parent / "ux"
QUEUE_LIMIT = 50


class NotFound(Exception):
    pass


def resolve_token_file(env: dict[str, str] | None = None, ext_id: str = EXTENSION_ID) -> Path:
    """Same lookup order as hermes-webui ``docs/EXTENSIONS.md`` (sidecar proxy auth)."""
    env = dict(os.environ) if env is None else env
    if env.get("HERMES_EXT_SIDECAR_TOKEN_FILE"):
        return Path(env["HERMES_EXT_SIDECAR_TOKEN_FILE"]).expanduser()
    name = Path("sidecar-auth") / f"{ext_id}.token"
    if env.get("HERMES_WEBUI_STATE_DIR"):
        return Path(env["HERMES_WEBUI_STATE_DIR"]).expanduser() / name
    if env.get("HERMES_HOME"):
        return Path(env["HERMES_HOME"]).expanduser() / "webui" / name
    if os.name == "nt" and env.get("LOCALAPPDATA"):
        return Path(env["LOCALAPPDATA"]) / "hermes" / "webui" / name
    return Path.home() / ".hermes" / "webui" / name


def load_layout(persona: str, ux_dir: Path = UX_DIR) -> dict[str, Any]:
    """Return the persona layout with each panel expanded from the catalogue."""
    if not PERSONA_RE.match(persona):
        raise ValueError(f"Invalid persona id {persona!r}")
    catalog = json.loads((ux_dir / "catalog.json").read_text(encoding="utf-8"))["panels"]
    layout = json.loads((ux_dir / f"{persona}.json").read_text(encoding="utf-8"))
    panels = []
    for panel_id in layout["panels"]:
        spec = catalog[panel_id]
        panel = {"id": panel_id, "title": spec["title"], "available": spec["status"] == "available"}
        if panel["available"]:
            panel["route"] = spec["route"]
        else:
            panel["reason"] = f"Planned for phase {spec['phase']}; no data source yet."
        if spec.get("advisory"):
            panel["advisory"] = True
        panels.append(panel)
    return {**layout, "panels": panels}


@dataclass(frozen=True)
class SidecarConfig:
    persona: str
    state_db: Path | None
    token_file: Path
    ux_dir: Path = UX_DIR


class PersonaData:
    """Read-only queries, always scoped to one persona."""

    def __init__(self, config: SidecarConfig) -> None:
        self.config = config

    def _connect(self) -> sqlite3.Connection:
        db = self.config.state_db
        if db is None or not db.is_file():
            raise FileNotFoundError("PersonaDesk state database is not available.")
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def queue(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT job_id, fixture_id, task, status, created_at, updated_at FROM jobs"
                " WHERE client_id = ? ORDER BY created_at DESC, job_id LIMIT ?",
                (self.config.persona, QUEUE_LIMIT),
            ).fetchall()
        return [dict(r) for r in rows]

    def _awaiting(self, conn: sqlite3.Connection, job_id: str | None) -> list[sqlite3.Row]:
        sql = (
            "SELECT j.job_id, j.fixture_id, j.task, d.draft_id, d.revision, d.body,"
            " d.evidence, d.uncertainties, d.blocked_actions, d.artifact_hash, d.created_at"
            " FROM jobs j JOIN drafts d ON d.job_id = j.job_id AND d.client_id = j.client_id"
            " WHERE j.client_id = ? AND j.status = 'awaiting_review'"
            " AND d.revision = (SELECT MAX(revision) FROM drafts WHERE job_id = j.job_id)"
        )
        params: list[Any] = [self.config.persona]
        if job_id is not None:
            sql += " AND j.job_id = ?"
            params.append(job_id)
        return conn.execute(sql + " ORDER BY d.created_at DESC, j.job_id", params).fetchall()

    def drafts(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = self._awaiting(conn, None)
        out = []
        for r in rows:
            item = dict(r)
            for key in ("evidence", "uncertainties", "blocked_actions"):
                item[key] = json.loads(item[key])
            out.append(item)
        return out

    def evidence(self, job_id: str | None) -> list[dict[str, Any]]:
        if job_id is not None and not JOB_ID_RE.match(job_id):
            raise NotFound("Unknown job.")
        with closing(self._connect()) as conn:
            rows = self._awaiting(conn, job_id)
        if job_id is not None and not rows:
            raise NotFound("Unknown job.")
        out = []
        for r in rows:
            for item in json.loads(r["evidence"]):
                out.append({"job_id": r["job_id"], "draft_id": r["draft_id"], **item})
        return out


class SidecarHandler(BaseHTTPRequestHandler):
    server_version = "PersonaDeskSidecar/1"
    config: SidecarConfig  # set by make_server

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("PD_SIDECAR_VERBOSE"):
            super().log_message(fmt, *args)

    def _send(self, status: int, payload: dict[str, Any], extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _reject_method(self) -> None:
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read-only sidecar: GET only"},
                   {"Allow": "GET"})

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _reject_method

    def _authorised(self) -> bool:
        try:
            expected = self.config.token_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE,
                       {"error": "sidecar token not provisioned; enable proxy consent in WebUI"})
            return False
        supplied = self.headers.get(TOKEN_HEADER, "")
        if not TOKEN_RE.match(expected) or not hmac.compare_digest(
            supplied.encode("utf-8"), expected.encode("utf-8")
        ):
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "missing or invalid sidecar token"})
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        url = urlsplit(self.path)
        if url.path == "/health":
            # WebUI's Settings -> Extensions monitor probes /health straight from the browser
            # (cross-origin). Only this data-free route allows that.
            self._send(HTTPStatus.OK, {"ok": True, "extension": EXTENSION_ID},
                       {"Access-Control-Allow-Origin": "*"})
            return
        if not self._authorised():
            return
        data = PersonaData(self.config)
        try:
            if url.path == "/v1/layout":
                payload: dict[str, Any] = {"layout": load_layout(self.config.persona, self.config.ux_dir)}
            elif url.path == "/v1/queue":
                payload = {"persona": self.config.persona, "jobs": data.queue()}
            elif url.path == "/v1/drafts":
                payload = {"persona": self.config.persona, "drafts": data.drafts()}
            elif url.path == "/v1/evidence":
                job_id = (parse_qs(url.query).get("job_id") or [None])[0]
                payload = {"persona": self.config.persona, "evidence": data.evidence(job_id)}
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "unknown route"})
                return
        except NotFound as exc:
            self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        except FileNotFoundError as exc:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
            return
        self._send(HTTPStatus.OK, payload)


def make_server(config: SidecarConfig, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    load_layout(config.persona, config.ux_dir)  # fail fast on an unknown persona
    handler = type("BoundSidecarHandler", (SidecarHandler,), {"config": config})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PersonaDesk read-only Workbench sidecar")
    parser.add_argument("--persona", default=os.environ.get("PD_SIDECAR_PERSONA"),
                        required=not os.environ.get("PD_SIDECAR_PERSONA"))
    parser.add_argument("--state-db", default=os.environ.get("PERSONADESK_STATE_DB"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PD_SIDECAR_PORT", DEFAULT_PORT)))
    args = parser.parse_args(argv)
    config = SidecarConfig(
        persona=args.persona,
        state_db=Path(args.state_db).expanduser() if args.state_db else None,
        token_file=resolve_token_file(),
    )
    server = make_server(config, args.port)
    print(f"PersonaDesk sidecar for {config.persona} on http://127.0.0.1:{args.port}"
          f" (token file: {config.token_file})", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
