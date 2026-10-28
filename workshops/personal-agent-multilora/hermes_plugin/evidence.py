"""Persona-scoped evidence: fixtures and approved policy excerpts.

Every read is resolved from a validated ID under a fixed directory for the *bound* persona,
so a tool argument can never name another persona's file or escape the workshop tree.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .paths import safe_child
from .permissions import PermissionDenied, PersonaGrant, require_id

FIXTURE_FIELDS = (
    "id", "client_id", "version", "split", "source_event_id", "from", "subject", "body",
    "received_at", "as_of", "facts", "expected",
)


def content_hash(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Fixture:
    data: dict[str, Any]
    sha: str

    @property
    def id(self) -> str:
        return self.data["id"]

    def reference(self) -> dict[str, Any]:
        return {
            "kind": "fixture",
            "owner": self.data["client_id"],
            "source_id": self.data["source_event_id"],
            "fixture_id": self.id,
            "fixture_version": self.data["version"],
            "content_hash": self.sha,
            "as_of": self.data["as_of"],
        }

    def model_view(self) -> dict[str, Any]:
        """What the controller may see: the message and facts, never the grading key."""
        return {k: self.data[k] for k in FIXTURE_FIELDS if k != "expected"}


def load_fixture(root: Path, grant: PersonaGrant, fixture_id: object) -> Fixture:
    fixture_id = require_id(fixture_id, "fixture_id")
    # Mail intake writes runtime fixtures (``mail-*``) under artifacts/inbox, never fixtures/.
    base = root / "artifacts" / "inbox" if fixture_id.startswith("mail-") else root / "fixtures"
    path = safe_child(base, grant.client_id, f"{fixture_id}.json")
    if not path.is_file():
        raise FileNotFoundError(f"Fixture '{fixture_id}' not found for {grant.client_id}.")
    raw = path.read_bytes()
    data = json.loads(raw)
    missing = [k for k in FIXTURE_FIELDS if k not in data]
    if missing:
        raise ValueError(f"Fixture '{fixture_id}' is missing fields: {missing}")
    if data["id"] != fixture_id or data["client_id"] != grant.client_id:
        raise PermissionDenied("Fixture identity does not match the bound persona.")
    return Fixture(data=data, sha=content_hash(raw))


@dataclass(frozen=True)
class Policy:
    policy_id: str
    version: int
    owner: str
    parameters: dict[str, Any]
    text: str
    sha: str

    def reference(self) -> dict[str, Any]:
        return {
            "kind": "policy",
            "owner": self.owner,
            "source_id": f"policy:{self.policy_id}",
            "policy_version": self.version,
            "content_hash": self.sha,
        }


def _split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    if not raw.startswith("---"):
        raise ValueError("Policy file must start with YAML front matter.")
    _, header, body = raw.split("---", 2)
    return YAML(typ="safe", pure=True).load(header) or {}, body.strip()


def load_policy(root: Path, grant: PersonaGrant, policy_id: object) -> Policy:
    policy_id = require_id(policy_id, "policy_id")
    grant.require("policy", policy_id)
    path = safe_child(root / "policies", grant.client_id, f"{policy_id}.md")
    raw = path.read_text(encoding="utf-8")
    meta, body = _split_front_matter(raw)
    if meta.get("id") != policy_id or meta.get("owner") != grant.client_id:
        raise PermissionDenied("Policy identity does not match the bound persona.")
    return Policy(
        policy_id=policy_id,
        version=int(meta["version"]),
        owner=meta["owner"],
        parameters=meta.get("parameters") or {},
        text=body,
        sha=content_hash(raw),
    )


def load_policy_parameters(root: Path, grant: PersonaGrant) -> dict[str, dict[str, Any]]:
    return {pid: load_policy(root, grant, pid).parameters for pid in grant.policies}
