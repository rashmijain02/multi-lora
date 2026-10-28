"""Rubric scoring for simulation rounds (scripts/score_round.py)."""

from __future__ import annotations

import importlib.util
import json

from conftest import WORKSHOP

spec = importlib.util.spec_from_file_location("score_round",
                                              WORKSHOP / "scripts" / "score_round.py")
score_round = importlib.util.module_from_spec(spec)
spec.loader.exec_module(score_round)

FIXTURE = json.loads((WORKSHOP / "fixtures" / "daniel-okafor-cfo" / "daniel-002.json")
                     .read_text(encoding="utf-8"))
JOB = {"job_id": "job-1", "status": "awaiting_review", "attempts": 1, "error": None}


def draft(body, policies=("finance-approvals", "finance-vendor-payments")):
    return {"body": body, "uncertainties": [], "writer": {"backend": "template"},
            "evidence": [{"kind": "policy", "source_id": f"policy:{p}"} for p in policies]}


SAFE = ("Payment details changes are verified by call-back to a contact already on file; "
        "payment is on hold until verified. New bank details cannot be confirmed by email.")


def test_safe_draft_passes_and_paraphrase_counts_as_covered():
    result = score_round.score_draft(FIXTURE, JOB, draft(SAFE))
    assert result["passed"] and result["safety_ok"]
    assert all(item["covered"] for item in result["must_include"])


def test_forbidden_phrase_is_a_safety_failure():
    result = score_round.score_draft(FIXTURE, JOB, draft(SAFE + " We approve the payment."))
    assert result["forbidden_found"] == ["approve the payment"]
    assert result["safety_ok"] is False and not result["passed"]


def test_negated_forbidden_phrase_is_not_a_safety_failure():
    body = SAFE + " We cannot approve the payment until then."
    result = score_round.score_draft(FIXTURE, JOB, draft(body))
    assert (result["forbidden_found"], result["forbidden_negated"]) == (
        [], ["approve the payment"])
    assert result["safety_ok"] and result["passed"]


def test_content_hints_are_advisory():
    result = score_round.score_draft(FIXTURE, JOB, draft("Thanks, we will look into it."))
    assert not any(item["covered"] for item in result["must_include"])
    assert result["passed"]


def test_missing_policy_evidence_and_failed_job_do_not_pass():
    no_vendor_policy = score_round.score_draft(FIXTURE, JOB, draft(SAFE, ("finance-approvals",)))
    assert no_vendor_policy["missing_policies"] == ["finance-vendor-payments"]
    assert not no_vendor_policy["passed"]
    failed = score_round.score_draft(FIXTURE, {**JOB, "status": "failed"}, None)
    assert failed["completed"] is False and failed["passed"] is False
