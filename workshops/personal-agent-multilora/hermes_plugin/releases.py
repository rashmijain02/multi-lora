"""Versioned persona releases: memory, skill, and adapter versions behind one pointer.

Manifests are immutable once written. Promotion needs a passing evaluation and an approver
who did not create the candidate; rollback re-points to the previous verified manifest.
Nothing here is model-callable.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evidence import content_hash
from .paths import safe_child
from .permissions import require_id


class ReleaseError(Exception):
    pass


def _dir(root: Path, client_id: str) -> Path:
    path = safe_child(root / "artifacts" / "releases", require_id(client_id, "client_id"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _canonical(manifest: dict[str, Any]) -> str:
    body = {k: v for k, v in manifest.items() if k != "manifest_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _write_once(path: Path, text: str) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def _file_digest(root: Path, relative: str) -> str:
    path = safe_child(root, *Path(relative).parts)
    return content_hash(path.read_bytes())


def create_candidate(
    root: Path, *, client_id: str, created_by: str, components: dict[str, Any],
    evaluation_report: str, base: dict[str, str], policy_version: str,
) -> dict[str, Any]:
    """``components`` maps kind -> {"path": workshop-relative file, ...}; digests are added."""
    directory = _dir(root, client_id)
    resolved = {}
    for kind, item in components.items():
        if kind not in ("memory", "skills", "adapter"):
            raise ReleaseError(f"Unknown component kind '{kind}'.")
        resolved[kind] = {**item, "sha": _file_digest(root, item["path"])}
    report = json.loads(safe_child(root, *Path(evaluation_report).parts).read_text("utf-8"))
    manifest = {
        "release_id": "rel-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
                      + "-" + uuid.uuid4().hex[:6],
        "client_id": client_id,
        "created_by": created_by,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "parent_release": (active_release(root, client_id) or {}).get("release_id"),
        "components": resolved,
        "base": base,
        "policy_version": policy_version,
        "evaluation": {"report": evaluation_report,
                       "sha": _file_digest(root, evaluation_report),
                       "passed": bool(report.get("passed"))},
    }
    manifest["manifest_hash"] = content_hash(_canonical(manifest))
    _write_once(directory / f"{manifest['release_id']}.json", json.dumps(manifest, indent=2))
    return manifest


def load_release(root: Path, client_id: str, release_id: str) -> dict[str, Any]:
    path = safe_child(_dir(root, client_id), f"{require_id(release_id, 'release_id')}.json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_hash") != content_hash(_canonical(manifest)):
        raise ReleaseError(f"Release {release_id} manifest hash mismatch (tampered?).")
    for kind, item in manifest["components"].items():
        if _file_digest(root, item["path"]) != item["sha"]:
            raise ReleaseError(f"Release {release_id} component '{kind}' checksum mismatch.")
    return manifest


def _pointer(root: Path, client_id: str) -> Path:
    return _dir(root, client_id) / "ACTIVE.json"


def active_release(root: Path, client_id: str) -> dict[str, Any] | None:
    pointer = _pointer(root, client_id)
    if not pointer.is_file():
        return None
    data = json.loads(pointer.read_text(encoding="utf-8"))
    manifest = load_release(root, client_id, data["release_id"])
    if manifest["manifest_hash"] != data["manifest_hash"]:
        raise ReleaseError("Active pointer does not match its manifest.")
    return {**manifest, "previous_active": data.get("previous")}


def _set_active(root: Path, client_id: str, manifest: dict[str, Any], **extra: Any) -> None:
    current = active_release(root, client_id)
    data = {
        "release_id": manifest["release_id"],
        "manifest_hash": manifest["manifest_hash"],
        "previous": current["release_id"] if current else None,
        "changed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **extra,
    }
    tmp = _pointer(root, client_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, _pointer(root, client_id))


def promote(root: Path, client_id: str, release_id: str, approver: str) -> dict[str, Any]:
    manifest = load_release(root, client_id, release_id)
    if not manifest["evaluation"]["passed"]:
        raise ReleaseError("Evaluation did not pass; promotion refused.")
    if approver == manifest["created_by"]:
        raise ReleaseError("The candidate's creator cannot approve its own release.")
    if _file_digest(root, manifest["evaluation"]["report"]) != manifest["evaluation"]["sha"]:
        raise ReleaseError("Evaluation report changed after the candidate was created.")
    _set_active(root, client_id, manifest, approver=approver, action="promote")
    return active_release(root, client_id)


def rollback(root: Path, client_id: str, approver: str) -> dict[str, Any]:
    current = active_release(root, client_id)
    if current is None or not current.get("previous_active"):
        raise ReleaseError("No previous release to roll back to.")
    target = load_release(root, client_id, current["previous_active"])
    _set_active(root, client_id, target, approver=approver, action="rollback")
    return active_release(root, client_id)


def list_releases(root: Path, client_id: str) -> list[str]:
    return sorted(p.stem for p in _dir(root, client_id).glob("rel-*.json"))
