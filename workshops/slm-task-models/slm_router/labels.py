"""Router label space, copied from PersonaDesk and kept in sync by tests.

``CHECKS`` mirrors ``hermes_plugin/checks.py::CHECKS`` (check -> owning policy) and
``PERSONA_POLICIES`` mirrors the ``policies/<persona>/`` folders. A persona may only run checks
whose policy it owns; ``persona_mask`` enforces that after any model prediction, so a model can
narrow a persona's checks but never widen them.
"""

from __future__ import annotations

CHECKS: dict[str, str] = {
    "sla_status": "support-escalation",
    "refund_eligibility": "support-refunds",
    "invoice_po_match": "finance-approvals",
    "approval_threshold": "finance-approvals",
    "calendar_conflict": "calendar-etiquette",
    "travel_policy": "travel-policy",
}
CHECK_ORDER: tuple[str, ...] = tuple(CHECKS)

PERSONA_POLICIES: dict[str, tuple[str, ...]] = {
    "daniel-okafor-cfo": ("finance-approvals", "finance-vendor-payments"),
    "noah-williams-assistant": ("calendar-etiquette", "travel-policy"),
    "priya-raman-support": ("support-escalation", "support-refunds"),
}
PERSONAS: tuple[str, ...] = tuple(PERSONA_POLICIES)


def allowed_checks(persona: str) -> tuple[str, ...]:
    if persona not in PERSONA_POLICIES:
        raise ValueError(f"unknown persona: {persona}")
    owned = PERSONA_POLICIES[persona]
    return tuple(check for check in CHECK_ORDER if CHECKS[check] in owned)


def canonical(checks) -> list[str]:
    """Deduplicate and order checks as in ``CHECK_ORDER``; reject unknown names."""
    names = set(checks)
    unknown = names - set(CHECK_ORDER)
    if unknown:
        raise ValueError(f"unknown checks: {sorted(unknown)}")
    return [check for check in CHECK_ORDER if check in names]


def persona_mask(persona: str, checks) -> tuple[list[str], list[str]]:
    """Split predicted checks into (kept, dropped_out_of_scope) for this persona."""
    allowed = set(allowed_checks(persona))
    ordered = canonical(checks)
    return ([c for c in ordered if c in allowed], [c for c in ordered if c not in allowed])
