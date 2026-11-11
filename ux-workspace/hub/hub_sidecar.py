"""Workshop Hub sidecar for the UX workspace.

The hermes-webui ``workshop-hub`` extension cannot add backend routes, so its data comes from
this small loopback service. WebUI's same-origin proxy forwards browser requests from
``/api/extensions/workshop-hub/sidecar/<path>`` to it and adds the ``X-Hermes-Sidecar-Token``
header (``proxy_auth: token-v1``).

What it serves, read only:

* ``/v1/workshops``: every valid ``workshops/<dir>/workshop.json``, sorted by ``order``, plus
  the validation errors of the invalid ones so workshop authors can see what to fix.
* ``/v1/workshops/<id>``: one manifest, with readiness checks (does each declared path exist?).
* ``/v1/workshops/<id>/doc?path=<p>``: the text of a markdown file **only if** ``p`` is listed
  in that workshop's ``docs``.

Rules this service enforces:

* Binds to 127.0.0.1 only, and only ``GET`` is allowed (405 for every other method).
* Every route except ``/health`` needs the token-v1 secret: 503 if the token file does not
  exist yet, 401 if the header is missing or wrong. The file is re-read per request so
  WebUI can rotate it.
* It never runs commands. Commands in manifests are text for the learner to copy.

Run (from the repository root):

    python ux-workspace/hub/hub_sidecar.py
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

EXTENSION_ID = "workshop-hub"
TOKEN_HEADER = "X-Hermes-Sidecar-Token"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,256}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFAULT_PORT = 8766
REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "workshop.json"
MAX_DOC_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 64 * 1024

STATUSES = ("built", "partial", "planned")
COMMAND_KINDS = ("setup", "check", "try")
ALLOWED_KEYS = {
    "schema", "id", "order", "label", "title", "summary", "status", "optional", "hardware",
    "builds_on", "docs", "readiness", "commands", "prompts", "extensions",
}
REQUIRED_KEYS = ("schema", "id", "order", "label", "title", "summary", "status", "optional",
                 "hardware", "docs")


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


# ---- manifest validation -------------------------------------------------------------------

def _is_safe_relative(value: object, *, allow_dot: bool = False) -> bool:
    """A forward-slash path relative to some root that cannot climb out of it."""
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        return False
    if allow_dot and value == ".":
        return True
    path = PurePosixPath(value)
    if path.is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _text(value: object, limit: int | None = None) -> bool:
    return isinstance(value, str) and bool(value.strip()) and (limit is None or len(value) <= limit)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def validate_manifest(data: object, folder: Path) -> list[str]:
    """Return human-readable problems with one manifest; an empty list means valid.

    ``builds_on`` targets are checked later by :func:`load_registry`, which knows every id.
    """
    if not isinstance(data, dict):
        return ["the file must contain a JSON object"]
    errors: list[str] = []
    for key in sorted(set(data) - ALLOWED_KEYS):
        errors.append(f"unknown field '{key}'")
    for key in REQUIRED_KEYS:
        if key not in data:
            errors.append(f"missing required field '{key}'")
    if errors:
        return errors

    if data["schema"] != 1:
        errors.append("'schema' must be 1")
    if not isinstance(data["id"], str) or not SLUG_RE.match(data["id"]):
        errors.append("'id' must be a lower-case slug such as 'my-workshop'")
    elif data["id"] != folder.name:
        errors.append(f"'id' must equal the folder name '{folder.name}'")
    if not isinstance(data["order"], int) or isinstance(data["order"], bool):
        errors.append("'order' must be an integer")
    for key in ("label", "title", "hardware"):
        if not _text(data[key], 120 if key != "hardware" else 200):
            errors.append(f"'{key}' must be non-empty text")
    if not _text(data["summary"], 400):
        errors.append("'summary' must be non-empty text of at most 400 characters")
    if data["status"] not in STATUSES:
        errors.append(f"'status' must be one of {', '.join(STATUSES)}")
    if not isinstance(data["optional"], bool):
        errors.append("'optional' must be true or false")

    builds_on = data.get("builds_on", [])
    if not isinstance(builds_on, list) or not all(isinstance(x, str) and SLUG_RE.match(x) for x in builds_on):
        errors.append("'builds_on' must be a list of workshop ids")
    elif data["id"] in builds_on:
        errors.append("'builds_on' must not list the workshop itself")

    docs = data["docs"]
    if not isinstance(docs, list) or not docs:
        errors.append("'docs' must be a non-empty list")
    else:
        seen: set[str] = set()
        for i, doc in enumerate(docs):
            where = f"docs[{i}]"
            if not isinstance(doc, dict) or set(doc) != {"path", "title"}:
                errors.append(f"{where} must have exactly 'path' and 'title'")
                continue
            path = doc["path"]
            if not _is_safe_relative(path) or not path.endswith(".md"):
                errors.append(f"{where}.path must be a relative '.md' path inside docs/<workshop-id>")
                continue
            if path in seen:
                errors.append(f"{where}.path '{path}' is listed twice")
            seen.add(path)
            repo_root = folder.parent.parent
            doc_folder = repo_root / "docs" / folder.name
            target = doc_folder / path
            if not _inside(doc_folder, repo_root) or not _inside(target, doc_folder) or not target.is_file():
                errors.append(f"{where}.path '{path}' does not exist")
            if not _text(doc["title"], 120):
                errors.append(f"{where}.title must be non-empty text")

    readiness = data.get("readiness", [])
    if not isinstance(readiness, list):
        errors.append("'readiness' must be a list")
    else:
        for i, item in enumerate(readiness):
            if (not isinstance(item, dict) or set(item) != {"label", "path"}
                    or not _text(item["label"], 120) or not _is_safe_relative(item["path"])):
                errors.append(f"readiness[{i}] must have 'label' and a repository-relative 'path' without '..'")

    commands = data.get("commands", [])
    if not isinstance(commands, list):
        errors.append("'commands' must be a list")
    else:
        for i, cmd in enumerate(commands):
            where = f"commands[{i}]"
            if not isinstance(cmd, dict) or not {"kind", "label", "cwd", "run"} <= set(cmd) \
                    or not set(cmd) <= {"kind", "label", "cwd", "run", "note"}:
                errors.append(f"{where} must have 'kind', 'label', 'cwd', 'run' and optionally 'note'")
                continue
            if cmd["kind"] not in COMMAND_KINDS:
                errors.append(f"{where}.kind must be one of {', '.join(COMMAND_KINDS)}")
            if not _text(cmd["label"], 120) or not _text(cmd["run"], 1000):
                errors.append(f"{where} needs non-empty 'label' and 'run'")
            if not _is_safe_relative(cmd["cwd"], allow_dot=True):
                errors.append(f"{where}.cwd must be '.' or a repository-relative path without '..'")
            if "note" in cmd and not _text(cmd["note"], 400):
                errors.append(f"{where}.note must be non-empty text")

    prompts = data.get("prompts", [])
    if not isinstance(prompts, list) or not all(
        isinstance(p, dict) and set(p) == {"label", "prompt"} and _text(p["label"], 120)
        and _text(p["prompt"], 2000) for p in prompts
    ):
        errors.append("'prompts' must be a list of {label, prompt} with non-empty text")

    extensions = data.get("extensions", [])
    if not isinstance(extensions, list) or not all(isinstance(x, str) and SLUG_RE.match(x) for x in extensions):
        errors.append("'extensions' must be a list of extension ids")
    return errors


@dataclass
class Registry:
    workshops: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def get(self, workshop_id: str) -> dict[str, Any]:
        for item in self.workshops:
            if item["id"] == workshop_id:
                return item
        raise NotFound("Unknown workshop.")


def load_registry(repo_root: Path) -> Registry:
    """Discover ``workshops/*/workshop.json``. Invalid manifests go to ``errors``, not the list."""
    registry = Registry()
    workshops_dir = repo_root / "workshops"
    candidates: list[dict[str, Any]] = []
    for folder in sorted(p for p in workshops_dir.iterdir() if p.is_dir()) if workshops_dir.is_dir() else []:
        manifest = folder / MANIFEST_NAME
        if not manifest.is_file():
            continue
        rel = f"workshops/{folder.name}/{MANIFEST_NAME}"
        try:
            if manifest.stat().st_size > MAX_MANIFEST_BYTES:
                raise ValueError("file is larger than 64 KB")
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (ValueError, OSError, UnicodeDecodeError) as exc:
            registry.errors.append({"manifest": rel, "errors": [f"cannot read JSON: {exc}"]})
            continue
        problems = validate_manifest(data, folder)
        if problems:
            registry.errors.append({"manifest": rel, "errors": problems})
            continue
        candidates.append(data)

    ids = {c["id"] for c in candidates}
    for data in candidates:
        missing = [x for x in data.get("builds_on", []) if x not in ids]
        if missing:
            registry.errors.append({
                "manifest": f"workshops/{data['id']}/{MANIFEST_NAME}",
                "errors": [f"'builds_on' names unknown workshop '{x}'" for x in missing],
            })
            continue
        registry.workshops.append(data)
    registry.workshops.sort(key=lambda w: (w["order"], w["id"]))
    return registry


# ---- views ---------------------------------------------------------------------------------

SUMMARY_KEYS = ("id", "order", "label", "title", "summary", "status", "optional", "hardware")


def workshop_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data[key] for key in SUMMARY_KEYS}


def workshop_detail(data: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    readiness = [
        {**item, "present": _inside(repo_root / item["path"], repo_root) and (repo_root / item["path"]).exists()}
        for item in data.get("readiness", [])
    ]
    return {
        **workshop_summary(data),
        "folder": f"workshops/{data['id']}",
        "builds_on": data.get("builds_on", []),
        "docs": data["docs"],
        "readiness": readiness,
        "commands": data.get("commands", []),
        "prompts": data.get("prompts", []),
        "extensions": data.get("extensions", []),
    }


class DocTooLarge(Exception):
    pass


def read_doc(data: dict[str, Any], requested: str | None, repo_root: Path) -> dict[str, Any]:
    """Return a declared doc. The request is matched exactly against ``docs``; nothing else is read."""
    declared = {doc["path"]: doc["title"] for doc in data["docs"]}
    if not requested or requested not in declared:
        raise NotFound("That document is not listed in the workshop's manifest.")
    folder = repo_root / "docs" / data["id"]
    target = folder / requested
    if not _inside(folder, repo_root) or not _inside(target, folder) or not target.is_file():
        raise NotFound("Document missing.")
    if target.stat().st_size > MAX_DOC_BYTES:
        raise DocTooLarge("Document is larger than 512 KB.")
    return {
        "workshop": data["id"],
        "path": requested,
        "title": declared[requested],
        "markdown": target.read_text(encoding="utf-8", errors="replace"),
    }


# ---- HTTP ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class HubConfig:
    repo_root: Path
    token_file: Path


WORKSHOP_ROUTE = re.compile(r"^/v1/workshops/([^/]+)(/doc)?$")


class HubHandler(BaseHTTPRequestHandler):
    server_version = "WorkshopHubSidecar/1"
    config: HubConfig  # set by make_server

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("HUB_SIDECAR_VERBOSE"):
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

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/health":
            # WebUI's Settings -> Extensions monitor probes /health straight from the browser
            # (cross-origin). Only this data-free route allows that.
            self._send(HTTPStatus.OK, {"ok": True, "extension": EXTENSION_ID},
                       {"Access-Control-Allow-Origin": "*"})
            return
        if not self._authorised():
            return
        root = self.config.repo_root
        try:
            registry = load_registry(root)
            if url.path == "/v1/workshops":
                payload: dict[str, Any] = {
                    "workshops": [workshop_summary(w) for w in registry.workshops],
                    "errors": registry.errors,
                }
            else:
                match = WORKSHOP_ROUTE.match(url.path)
                if not match:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "unknown route"})
                    return
                data = registry.get(unquote(match.group(1)))
                if match.group(2):
                    requested = (parse_qs(url.query).get("path") or [None])[0]
                    payload = read_doc(data, requested, root)
                else:
                    payload = workshop_detail(data, root)
        except NotFound as exc:
            self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        except DocTooLarge as exc:
            self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": str(exc)})
            return
        self._send(HTTPStatus.OK, payload)


def make_server(config: HubConfig, port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    handler = type("BoundHubHandler", (HubHandler,), {"config": config})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Workshop Hub read-only sidecar")
    parser.add_argument("--port", type=int, default=int(os.environ.get("HUB_SIDECAR_PORT", DEFAULT_PORT)))
    parser.add_argument("--check", action="store_true",
                        help="validate every workshop.json, print the result and exit (1 if any is invalid)")
    args = parser.parse_args(argv)
    if args.check:
        registry = load_registry(REPO_ROOT)
        for w in registry.workshops:
            print(f"ok    {w['order']:>2}  {w['id']}")
        for err in registry.errors:
            print(f"FAIL  {err['manifest']}")
            for line in err["errors"]:
                print(f"        - {line}")
        return 1 if registry.errors else 0
    config = HubConfig(repo_root=REPO_ROOT, token_file=resolve_token_file())
    server = make_server(config, args.port)
    print(f"Workshop Hub sidecar on http://127.0.0.1:{args.port} (token file: {config.token_file})",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
