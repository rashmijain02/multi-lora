"""Deterministic checks over the seed fixtures."""

from __future__ import annotations

from conftest import call, runtime


def check(root, db, profile, name, fixture_id):
    result = call(runtime(root, db, profile), "pd_run_check", check=name, fixture_id=fixture_id)
    assert result["ok"], result
    return result


def test_support_checks(root, db):
    sla = check(root, db, "pd-priya", "sla_status", "priya-001")
    assert (sla["outcome"], sla["escalate"]) == ("breached", True)
    refund = check(root, db, "pd-priya", "refund_eligibility", "priya-002")
    assert (refund["outcome"], refund["route"]) == ("eligible", "l1_recommend")
    assert check(root, db, "pd-priya", "sla_status", "priya-002")["escalate"] is False
    assert check(root, db, "pd-priya", "refund_eligibility", "priya-001")["outcome"] == \
        "not_applicable"


def test_finance_checks(root, db):
    match = check(root, db, "pd-daniel", "invoice_po_match", "daniel-001")
    assert (match["outcome"], match["difference"]) == ("mismatch", 550.0)
    approvers = check(root, db, "pd-daniel", "approval_threshold", "daniel-001")["approvers"]
    assert approvers == ["budget owner", "CFO"]
    fraud = check(root, db, "pd-daniel", "invoice_po_match", "daniel-002")
    assert (fraud["outcome"], fraud["payment_hold"]) == ("match", True)
    policies = {e["source_id"] for e in fraud["evidence"] if e["kind"] == "policy"}
    assert policies == {"policy:finance-approvals", "policy:finance-vendor-payments"}
    verified = check(root, db, "pd-daniel", "invoice_po_match", "daniel-003")
    assert "policy:finance-vendor-payments" not in str(verified["evidence"])
    assert check(root, db, "pd-daniel", "approval_threshold", "daniel-003")["approvers"] == \
        ["budget owner"]


def test_calendar_conflict_offers_alternatives_without_leaking_titles(root, db):
    result = check(root, db, "pd-noah", "calendar_conflict", "noah-001")
    assert result["outcome"] == "conflict"
    assert [a[11:16] for a in result["alternatives"]] == ["08:00", "11:00"]
    assert "Investor" not in str(result)


def test_travel_policy(root, db):
    result = check(root, db, "pd-noah", "travel_policy", "noah-002")
    assert result["outcome"] == "non_compliant"
    assert result["reasons"] == ["business_class_below_min_duration"]
    assert result["compliant_alternative"] == "economy"


def test_travel_policy_keeps_itinerary_internal_for_external_senders(root, db):
    external = check(root, db, "pd-noah", "travel_policy", "noah-003")
    assert (external["outcome"], external["share_itinerary"]) == ("external_request", False)
    assert external["pickup_channel"] == "company travel desk"
    # Internal mail without a fare is still outside the travel policy.
    assert check(root, db, "pd-noah", "travel_policy", "noah-001")["outcome"] == "not_applicable"


def test_refund_above_l1_limit_goes_to_billing_lead():
    from hermes_plugin.tools import brief_from_checks

    result = {"check": "refund_eligibility", "outcome": "eligible", "amount": 1200.0,
              "window_days": 30, "route": "billing_lead"}
    brief, _ = brief_from_checks(None, [result])
    assert "billing lead for a decision" in brief[0] and "recommended" not in brief[0]


def test_unknown_check_is_invalid(root, db):
    result = call(runtime(root, db, "pd-noah"), "pd_run_check", check="rm -rf",
                  fixture_id="noah-001")
    assert result["error"] == "invalid_request"
