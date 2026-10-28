"""Persona permissions and identity binding.

Identity comes from the *host*: the active Hermes profile (``ctx.profile_name``) and, for
operator commands, the local OS user checked against an allowlist. Nothing in an email, a
fixture, or a model-generated tool argument can select or widen a persona.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .paths import PERMISSIONS_RELATIVE

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
OPERATORS_RELATIVE = Path("config") / "operators.json"


class PermissionDenied(Exception):
    """Raised when a principal, profile, tool, task, policy, or check is not allowed."""


@dataclass(frozen=True)
class PersonaGrant:
    client_id: str
    hermes_profile: str
    writer_adapter: str
    tasks: tuple[str, ...]
    tools: tuple[str, ...]
    policies: tuple[str, ...]
    checks: tuple[str, ...]
    blocked_actions: tuple[str, ...]

    def require(self, kind: str, value: str) -> None:
        allowed = {
            "task": self.tasks,
            "tool": self.tools,
            "policy": self.policies,
            "check": self.checks,
        }[kind]
        if value not in allowed:
            raise PermissionDenied(f"{kind} '{value}' is not permitted for {self.client_id}.")


@dataclass(frozen=True)
class Permissions:
    version: str
    max_turns: int
    worker_timeout_seconds: int
    max_tool_output_chars: int
    max_task_chars: int
    personas: dict[str, PersonaGrant]

    def for_profile(self, profile_name: str | None) -> PersonaGrant:
        """Bind the persona from the active Hermes profile; unknown profiles get nothing."""
        if not profile_name:
            raise PermissionDenied("No active Hermes profile; PersonaDesk tools are disabled.")
        for grant in self.personas.values():
            if grant.hermes_profile == profile_name:
                return grant
        raise PermissionDenied(f"Profile '{profile_name}' is not bound to an enabled persona.")

    def is_bound_profile(self, profile_name: str | None) -> bool:
        return any(g.hermes_profile == profile_name for g in self.personas.values())


def load_permissions(root: Path) -> Permissions:
    raw = json.loads((root / PERMISSIONS_RELATIVE).read_text(encoding="utf-8-sig"))
    defaults = raw["defaults"]
    personas: dict[str, PersonaGrant] = {}
    profiles: set[str] = set()
    for client_id, item in raw["personas"].items():
        if not ID_PATTERN.match(client_id):
            raise ValueError(f"Invalid client_id in permissions: {client_id!r}")
        if not item.get("enabled"):
            continue
        profile = item["hermes_profile"]
        if profile in profiles:
            raise ValueError(f"Profile '{profile}' is mapped to more than one persona.")
        profiles.add(profile)
        personas[client_id] = PersonaGrant(
            client_id=client_id,
            hermes_profile=profile,
            writer_adapter=item["writer_adapter"],
            tasks=tuple(item["tasks"]),
            tools=tuple(item["tools"]),
            policies=tuple(item["policies"]),
            checks=tuple(item["checks"]),
            blocked_actions=tuple(item["blocked_actions"]),
        )
    return Permissions(
        version=raw["version"],
        max_turns=int(defaults["max_turns"]),
        worker_timeout_seconds=int(defaults["worker_timeout_seconds"]),
        max_tool_output_chars=int(defaults["max_tool_output_chars"]),
        max_task_chars=int(defaults["max_task_chars"]),
        personas=personas,
    )


def load_operators(root: Path) -> dict[str, tuple[str, ...]]:
    """Return ``{os_user: allowed client IDs}``. A missing file means nobody is allowed."""
    path = root / OPERATORS_RELATIVE
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return {user: tuple(ids) for user, ids in raw.get("operators", {}).items()}


def authorize_operator(
    operators: dict[str, tuple[str, ...]], principal: str, client_id: str
) -> None:
    if client_id not in operators.get(principal, ()):
        raise PermissionDenied(
            f"Operator '{principal}' may not act for '{client_id}'. "
            f"Add it to {OPERATORS_RELATIVE.as_posix()}."
        )


def require_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        raise ValueError(f"{label} must match {ID_PATTERN.pattern}.")
    return value
