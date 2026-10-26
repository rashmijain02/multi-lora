"""Deterministic business checks.

Checks are plain functions of fixture facts and policy parameters. The model can ask for a
named check; it cannot supply the numbers, so a prompt cannot talk a check into passing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

Facts = dict[str, Any]
Params = dict[str, Any]


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def sla_status(fixture: dict[str, Any], p: Params) -> dict[str, Any]:
    facts = fixture["facts"]
    plan = facts.get("plan")
    hours = p["first_response_sla_hours"].get(plan)
    if hours is None:
        return {"outcome": "unknown_plan", "plan": plan}
    elapsed = (_dt(fixture["as_of"]) - _dt(fixture["received_at"])).total_seconds() / 3600
    if elapsed > hours:
        outcome = "breached"
    elif elapsed >= 0.75 * hours:
        outcome = "at_risk"
    else:
        outcome = "within"
    return {
        "outcome": outcome,
        "plan": plan,
        "sla_hours": hours,
        "elapsed_hours": round(elapsed, 2),
        "escalate": bool(facts.get("error_code"))
        and (outcome != "within" or bool(facts.get("known_issue"))),
        "known_issue": facts.get("known_issue"),
        "error_code": facts.get("error_code"),
    }


def refund_eligibility(fixture: dict[str, Any], p: Params) -> dict[str, Any]:
    facts = fixture["facts"]
    amount, age = facts.get("order_amount"), facts.get("order_age_days")
    if amount is None or age is None:
        return {"outcome": "not_applicable"}
    eligible = age <= p["refund_window_days"]
    route = "l1_recommend" if eligible and amount <= p["l1_recommend_limit"] else "billing_lead"
    return {
        "outcome": "eligible" if eligible else "outside_window",
        "amount": amount,
        "order_age_days": age,
        "window_days": p["refund_window_days"],
        "route": route,
        "processed_by": "billing team",
    }


def invoice_po_match(fixture: dict[str, Any], p: Params) -> dict[str, Any]:
    facts = fixture["facts"]
    if facts.get("invoice_amount") is None or facts.get("po_amount") is None:
        return {"outcome": "not_applicable"}
    invoice, po = facts["invoice_amount"], facts["po_amount"]
    difference = round(invoice - po, 2)
    percent = abs(difference) / po * 100 if po else float("inf")
    matched = percent <= p["po_tolerance_percent"]
    return {
        "outcome": "match" if matched else "mismatch",
        "invoice_amount": invoice,
        "po_amount": po,
        "difference": difference,
        "difference_percent": round(percent, 2),
        "tolerance_percent": p["po_tolerance_percent"],
        "vendor_verified": facts.get("vendor_verified"),
        "payment_hold": not facts.get("vendor_verified", False),
    }


def approval_threshold(fixture: dict[str, Any], p: Params) -> dict[str, Any]:
    amount = fixture["facts"].get("invoice_amount")
    if amount is None:
        return {"outcome": "not_applicable"}
    for tier in p["approval_tiers"]:
        limit = tier["max_amount"]
        if limit is None or amount <= limit:
            return {"outcome": "routed", "amount": amount, "approvers": tier["approvers"]}
    raise ValueError("approval_tiers must end with an unbounded tier.")


def _overlaps(start: datetime, end: datetime, busy: list[dict[str, str]], buffer: timedelta):
    return [
        b for b in busy
        if start < _dt(b["end"]) + buffer and _dt(b["start"]) - buffer < end
    ]


def calendar_conflict(fixture: dict[str, Any], p: Params) -> dict[str, Any]:
    facts = fixture["facts"]
    if not facts.get("proposed_start"):
        return {"outcome": "not_applicable"}
    start = _dt(facts["proposed_start"])
    length = timedelta(minutes=facts["proposed_minutes"])
    buffer = timedelta(minutes=p["buffer_minutes"])
    busy = facts.get("busy", [])
    conflicts = _overlaps(start, start + length, busy, buffer)
    alternatives: list[str] = []
    if conflicts:
        open_h, open_m = map(int, p["working_hours"][0].split(":"))
        close_h, close_m = map(int, p["working_hours"][1].split(":"))
        slot = start.replace(hour=open_h, minute=open_m)
        close = start.replace(hour=close_h, minute=close_m)
        while slot + length <= close and len(alternatives) < 2:
            if slot != start and not _overlaps(slot, slot + length, busy, buffer):
                alternatives.append(slot.isoformat())
            slot += timedelta(minutes=30)
    return {
        "outcome": "conflict" if conflicts else "free",
        "proposed_start": start.isoformat(),
        "proposed_minutes": facts["proposed_minutes"],
        # Privacy: report conflicting windows, never their titles or attendees.
        "conflicts": [{"start": b["start"], "end": b["end"]} for b in conflicts],
        "alternatives": alternatives,
    }


def travel_policy(fixture: dict[str, Any], p: Params) -> dict[str, Any]:
    facts = fixture["facts"]
    fare_class = facts.get("fare_class")
    if not fare_class:
        return {"outcome": "not_applicable"}
    hours = facts.get("flight_hours")
    amount = facts.get("fare_amount")
    reasons = []
    if fare_class == "business" and (hours is None or hours < p["business_class_min_flight_hours"]):
        reasons.append("business_class_below_min_duration")
    cap = p["max_fare"].get(fare_class)
    if cap is None:
        reasons.append("unknown_fare_class")
    elif amount is not None and amount > cap:
        reasons.append("fare_above_cap_needs_cfo_approval")
    return {
        "outcome": "compliant" if not reasons else "non_compliant",
        "fare_class": fare_class,
        "fare_amount": amount,
        "flight_hours": hours,
        "min_business_hours": p["business_class_min_flight_hours"],
        "reasons": reasons,
        "compliant_alternative": "economy" if reasons else None,
        "requires_traveler_confirmation": True,
    }


CHECKS: dict[str, tuple[str, Callable[[dict[str, Any], Params], dict[str, Any]]]] = {
    "sla_status": ("support-escalation", sla_status),
    "refund_eligibility": ("support-refunds", refund_eligibility),
    "invoice_po_match": ("finance-approvals", invoice_po_match),
    "approval_threshold": ("finance-approvals", approval_threshold),
    "calendar_conflict": ("calendar-etiquette", calendar_conflict),
    "travel_policy": ("travel-policy", travel_policy),
}
