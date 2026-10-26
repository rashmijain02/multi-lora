"""Model-callable PersonaDesk tools and the pre_tool_call guard.

Every handler binds the persona from the active Hermes profile, validates IDs, returns
bounded JSON, and never raises (Hermes tool contract). No tool accepts a persona, path,
URL, model name, or shell text from the model.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import checks as checks_mod
from .classification import ClassifierSettings, classify
from .evidence import Fixture, load_fixture, load_policy
from .permissions import PermissionDenied, Permissions, PersonaGrant, load_permissions
from .store import Store, open_store
from .tasks import TOOLSET, bound_job, locks_dir
from .writer import Writer, WriterUnavailable, make_writer

TOOL_NAMES = (
    "pd_read_fixture", "pd_get_policy", "pd_run_check", "pd_draft_reply", "pd_classify_message",
)


@dataclass
class Runtime:
    root: Path
    settings: dict[str, Any]
    profile_name: Callable[[], str | None]
    store_factory: Callable[[], Store]
    permissions: Permissions = field(init=False)
    writer: Writer = field(init=False)
    _store: Store | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.permissions = load_permissions(self.root)
        self.writer = make_writer(self.settings)

    def grant(self) -> PersonaGrant:
        return self.permissions.for_profile(self.profile_name())

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = self.store_factory()
        return self._store

    def classifier_settings(self) -> ClassifierSettings:
        raw = dict(self.settings.get("classifier") or {})
        artifact = raw.get("lexical_artifact")
        if artifact and not Path(artifact).is_absolute():
            raw["lexical_artifact"] = str(self.root / artifact)
        return ClassifierSettings.from_mapping(raw)


def _json(payload: dict[str, Any], limit: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return json.dumps({"ok": payload.get("ok", True), "truncated": True,
                       "preview": text[: max(0, limit - 200)]})


def _error(kind: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": kind, "message": message}


def _guard(rt: Runtime, tool: str, fn: Callable[[PersonaGrant, dict[str, Any]], dict[str, Any]]):
    def handler(args: dict[str, Any] | None = None, **_kwargs: Any) -> str:
        limit = rt.permissions.max_tool_output_chars
        try:
            grant = rt.grant()
            grant.require("tool", tool)
            payload = fn(grant, dict(args or {}))
        except PermissionDenied as exc:
            payload = _error("permission_denied", str(exc))
        except (ValueError, KeyError, FileNotFoundError) as exc:
            payload = _error("invalid_request", str(exc))
        except WriterUnavailable as exc:
            payload = _error("writer_unavailable", str(exc))
        except Exception as exc:  # noqa: BLE001 - tools must never raise into Hermes
            payload = _error("internal_error", f"{type(exc).__name__}: {exc}")
        return _json(payload, limit)

    return handler


# ---- check helpers -------------------------------------------------------------------
def run_check(rt: Runtime, grant: PersonaGrant, check: str, fixture: Fixture) -> dict[str, Any]:
    if not isinstance(check, str) or check not in checks_mod.CHECKS:
        raise ValueError(f"Unknown check {check!r}.")
    grant.require("check", check)
    policy_id, fn = checks_mod.CHECKS[check]
    policy = load_policy(rt.root, grant, policy_id)
    result = fn(fixture.data, policy.parameters)
    return {"check": check, **result, "evidence": [fixture.reference(), policy.reference()]}


def brief_from_checks(fixture: Fixture, results: list[dict[str, Any]]) -> tuple[list, list]:
    """Turn verified check outcomes into writer instructions and open uncertainties."""
    brief: list[str] = []
    uncertain: list[str] = []
    for r in results:
        name, outcome = r["check"], r["outcome"]
        if outcome == "not_applicable":
            continue
        if name == "sla_status":
            if r.get("known_issue"):
                brief.append(f"This matches known issue {r['known_issue'].split(':')[0]}. "
                             "We cannot promise a fix date.")
            if r.get("escalate"):
                brief.append(f"Escalated to the product on-call queue; escalation reference "
                             f"ESC-{fixture.id.upper()}.")
            if r.get("escalate") or r.get("known_issue"):
                next_update = checks_mod._dt(fixture.data["as_of"]) + timedelta(hours=4)
                brief.append(f"Next status update by {next_update.isoformat()}.")
            if outcome == "unknown_plan":
                uncertain.append("Customer plan unknown; SLA not determined.")
        elif name == "refund_eligibility":
            if outcome == "eligible":
                brief.append(f"The ${r['amount']:.2f} charge is within the {r['window_days']}-day "
                             "refund window; refund recommended to the billing team, who process "
                             "all refunds and review within two business days.")
            else:
                brief.append("The charge is outside the refund window; forwarded to the billing "
                             "lead for a decision.")
        elif name == "invoice_po_match":
            if outcome == "mismatch":
                brief.append(f"Invoice ${r['invoice_amount']:,.2f} does not match PO "
                             f"${r['po_amount']:,.2f} (difference ${r['difference']:,.2f}); "
                             "please send a corrected invoice or an approved PO change.")
            else:
                brief.append("Invoice and PO amounts match (match confirmed).")
            if r.get("payment_hold"):
                brief.append("Payment details changes are verified by call-back to a contact "
                             "already on file; payment is on hold until verified. New bank "
                             "details cannot be confirmed by email.")
        elif name == "approval_threshold":
            brief.append(f"Standard approval route for ${r['amount']:,.2f}: "
                         f"{' and '.join(r['approvers'])} in the finance system.")
        elif name == "calendar_conflict":
            if outcome == "conflict":
                alts = r["alternatives"]
                brief.append("The requested time conflicts with an existing commitment. "
                             f"Alternatives: {', '.join(alts) if alts else 'none found today'}.")
                if len(alts) < 2:
                    uncertain.append("Fewer than two alternative times found.")
            else:
                brief.append("The requested time is available; awaiting confirmation before "
                             "sending any invite.")
        elif name == "travel_policy":
            if outcome == "non_compliant":
                brief.append(f"Policy check: {', '.join(r['reasons'])}. A "
                             f"{r['compliant_alternative']} fare is the compliant alternative.")
            brief.append("Please confirm before anything is booked.")
    return brief, uncertain


# ---- tool implementations ------------------------------------------------------------
def make_handlers(rt: Runtime) -> dict[str, Callable[..., str]]:
    def read_fixture(grant, args):
        fixture = load_fixture(rt.root, grant, args.get("fixture_id"))
        return {"ok": True, "fixture": fixture.model_view(), "evidence": fixture.reference()}

    def get_policy(grant, args):
        policy = load_policy(rt.root, grant, args.get("policy_id"))
        return {"ok": True, "policy_id": policy.policy_id, "text": policy.text,
                "parameters": policy.parameters, "evidence": policy.reference()}

    def run_check_tool(grant, args):
        fixture = load_fixture(rt.root, grant, args.get("fixture_id"))
        return {"ok": True, **run_check(rt, grant, args.get("check"), fixture)}

    def draft_reply(grant, args):
        binding = bound_job(locks_dir(rt.root), args.get("job_token"))
        if not binding or not binding.job_id:
            raise PermissionDenied(
                "pd_draft_reply needs the job token of the running PersonaDesk job.")
        own_store = bool(binding.state_db)
        store = open_store(Path(binding.state_db)) if own_store else rt.store
        try:
            return _draft_for_job(grant, args, store, binding.job_id)
        finally:
            if own_store:
                store.conn.close()

    def _draft_for_job(grant, args, store, job_id):
        job = store.get_job(job_id)
        fixture = load_fixture(rt.root, grant, args.get("fixture_id"))
        if job["status"] != "running" or job["client_id"] != grant.client_id \
                or job["fixture_id"] != fixture.id:
            raise PermissionDenied("Draft request does not match the bound job.")
        results = [run_check(rt, grant, c, fixture) for c in grant.checks]
        brief, uncertain = brief_from_checks(fixture, results)
        notes = str(args.get("uncertainties") or "")[:500]
        if notes:
            uncertain.append(f"Controller note: {notes}")
        body, writer_identity = rt.writer.generate(
            client_id=grant.client_id, adapter=grant.writer_adapter,
            subject=fixture.data["subject"], body=fixture.data["body"], brief=brief,
        )
        evidence = [fixture.reference()] + [
            ref for r in results if r["outcome"] != "not_applicable"
            for ref in r["evidence"] if ref["kind"] == "policy"
        ]
        draft = store.save_draft(
            job_id=job_id, client_id=grant.client_id, body=body,
            evidence=[dict(t) for t in {json.dumps(e, sort_keys=True): e
                                        for e in evidence}.values()],
            uncertainties=uncertain, blocked_actions=list(grant.blocked_actions),
            writer=writer_identity,
        )
        return {"ok": True, "draft_id": draft["draft_id"], "revision": draft["revision"],
                "artifact_hash": draft["artifact_hash"], "body": body,
                "checks": [{"check": r["check"], "outcome": r["outcome"]} for r in results],
                "uncertainties": uncertain, "writer": writer_identity,
                "note": "This stored draft is the review artifact; do not rewrite it."}

    def classify_message(grant, args):
        fixture = load_fixture(rt.root, grant, args.get("fixture_id"))
        taxonomy = args.get("taxonomy", "C10")
        if taxonomy not in ("C6", "C10"):
            raise ValueError("taxonomy must be C6 or C10.")
        record = classify(taxonomy, fixture.data["subject"], fixture.data["body"],
                          rt.classifier_settings())
        record["fixture_id"] = fixture.id
        record["authority"] = "advisory only: labels never authorize actions"
        return {"ok": record["status"] == "ok", "classification": record}

    impls = {
        "pd_read_fixture": read_fixture,
        "pd_get_policy": get_policy,
        "pd_run_check": run_check_tool,
        "pd_draft_reply": draft_reply,
        "pd_classify_message": classify_message,
    }
    return {name: _guard(rt, name, fn) for name, fn in impls.items()}


_FIXTURE = {"type": "string", "description": "Fixture ID, e.g. priya-001."}
SCHEMAS: dict[str, dict[str, Any]] = {
    "pd_read_fixture": {
        "name": "pd_read_fixture",
        "description": "Read one message fixture owned by the current persona.",
        "parameters": {"type": "object", "properties": {"fixture_id": _FIXTURE},
                       "required": ["fixture_id"], "additionalProperties": False},
    },
    "pd_get_policy": {
        "name": "pd_get_policy",
        "description": "Retrieve an approved policy for the current persona by policy ID.",
        "parameters": {"type": "object",
                       "properties": {"policy_id": {"type": "string"}},
                       "required": ["policy_id"], "additionalProperties": False},
    },
    "pd_run_check": {
        "name": "pd_run_check",
        "description": "Run a named deterministic check (e.g. sla_status) against a fixture.",
        "parameters": {"type": "object",
                       "properties": {"check": {"type": "string"}, "fixture_id": _FIXTURE},
                       "required": ["check", "fixture_id"], "additionalProperties": False},
    },
    "pd_draft_reply": {
        "name": "pd_draft_reply",
        "description": "Generate and store the persona's reply draft for human review. "
                       "Call once per job; the stored draft is the canonical artifact.",
        "parameters": {"type": "object",
                       "properties": {"fixture_id": _FIXTURE,
                                      "job_token": {"type": "string",
                                                    "description": "Job token from the task."},
                                      "uncertainties": {"type": "string",
                                                        "description": "Open questions."}},
                       "required": ["fixture_id", "job_token"], "additionalProperties": False},
    },
    "pd_classify_message": {
        "name": "pd_classify_message",
        "description": "Advisory typed classification of a fixture (C6 or C10).",
        "parameters": {"type": "object",
                       "properties": {"fixture_id": _FIXTURE,
                                      "taxonomy": {"type": "string", "enum": ["C6", "C10"]}},
                       "required": ["fixture_id"], "additionalProperties": False},
    },
}


def make_pre_tool_call(rt: Runtime) -> Callable[..., dict[str, str] | None]:
    """Block any tool a bound persona profile is not granted (defense in depth)."""
    extra = set(rt.settings.get("extra_allowed_tools") or [])

    def pre_tool_call(tool_name: str = "", args: Any = None, task_id: str = "", **_kw: Any):
        profile = rt.profile_name()
        if not rt.permissions.is_bound_profile(profile):
            return None
        grant = rt.permissions.for_profile(profile)
        if tool_name in grant.tools or tool_name in extra:
            return None
        return {"action": "block",
                "message": f"PersonaDesk: tool '{tool_name}' is not permitted for "
                           f"{grant.client_id}."}

    return pre_tool_call


__all__ = ["SCHEMAS", "TOOLSET", "TOOL_NAMES", "Runtime", "make_handlers", "make_pre_tool_call"]
