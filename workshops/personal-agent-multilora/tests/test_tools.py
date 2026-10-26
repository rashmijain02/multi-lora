"""Identity binding, scoped evidence, bounded tools, and the pre_tool_call guard."""

from __future__ import annotations

import dataclasses
import json

import pytest
from conftest import call, runtime

from hermes_plugin.permissions import PermissionDenied, load_permissions
from hermes_plugin.store import open_store
from hermes_plugin.tasks import job_binding, locks_dir
from hermes_plugin.tools import make_pre_tool_call


def test_profile_binds_exactly_one_persona(root):
    permissions = load_permissions(root)
    assert permissions.for_profile("pd-daniel").client_id == "daniel-okafor-cfo"
    for profile in (None, "", "default", "pd-maya"):  # pd-maya exists but is disabled
        with pytest.raises(PermissionDenied):
            permissions.for_profile(profile)


def test_duplicate_profile_mapping_is_rejected(root):
    path = root / "config" / "persona_permissions.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["personas"]["daniel-okafor-cfo"]["hermes_profile"] = "pd-priya"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="more than one persona"):
        load_permissions(root)


def test_read_fixture_hides_grading_key(root, db):
    result = call(runtime(root, db, "pd-priya"), "pd_read_fixture", fixture_id="priya-001")
    assert result["ok"]
    assert "expected" not in result["fixture"]
    assert result["evidence"]["content_hash"].startswith("sha256:")


@pytest.mark.parametrize("fixture_id", [
    "daniel-001",                              # another persona's fixture
    "../daniel-okafor-cfo/daniel-001",         # traversal
    "..",
    "PRIYA-001",
    None,
])
def test_fixture_reads_cannot_leave_bound_persona(root, db, fixture_id):
    result = call(runtime(root, db, "pd-priya"), "pd_read_fixture", fixture_id=fixture_id)
    assert result["ok"] is False
    assert result["error"] in ("invalid_request", "permission_denied")


def test_tools_deny_unbound_profile(root, db):
    result = call(runtime(root, db, "default"), "pd_read_fixture", fixture_id="priya-001")
    assert result == {"ok": False, "error": "permission_denied",
                      "message": "Profile 'default' is not bound to an enabled persona."}


def test_cross_persona_policy_and_check_are_denied(root, db):
    rt = runtime(root, db, "pd-priya")
    assert call(rt, "pd_get_policy", policy_id="finance-approvals")["error"] == \
        "permission_denied"
    result = call(rt, "pd_run_check", check="invoice_po_match", fixture_id="priya-001")
    assert result["error"] == "permission_denied"


def test_injected_fixture_instructions_do_not_widen_access(root, db):
    """priya-003 asks the agent to read Daniel's policy; the tool layer still refuses."""
    rt = runtime(root, db, "pd-priya")
    fixture = call(rt, "pd_read_fixture", fixture_id="priya-003")["fixture"]
    assert "Daniel Okafor" in fixture["body"]
    assert call(rt, "pd_get_policy", policy_id="finance-vendor-payments")["ok"] is False


def test_tool_output_is_bounded(root, db):
    rt = runtime(root, db, "pd-priya")
    rt.permissions = dataclasses.replace(rt.permissions, max_tool_output_chars=300)
    out = call(rt, "pd_read_fixture", fixture_id="priya-001")
    assert out["truncated"] is True and len(json.dumps(out)) < 400


def test_draft_tool_requires_job_context(root, db):
    result = call(runtime(root, db, "pd-priya"), "pd_draft_reply", fixture_id="priya-001")
    assert result["error"] == "permission_denied"


def test_draft_binds_only_with_the_running_jobs_token(root, db, tmp_path):
    rt = runtime(root, db, "pd-priya")
    job_store = open_store(tmp_path / "job-owner.db")  # the CLI's store, not the tool runtime's
    job, _ = job_store.create_job(source_key="k", principal="op",
                                  client_id="priya-raman-support", profile="pd-priya",
                                  fixture_id="priya-001", task="draft_reply", release_id=None)
    locks = locks_dir(root)
    locks.mkdir(parents=True, exist_ok=True)
    with job_binding(locks, job["job_id"], "secret-token", job_store.path):
        assert call(rt, "pd_draft_reply", fixture_id="priya-001",
                    job_token="secret-token")["error"] == "permission_denied"  # still queued
        job_store.transition(job["job_id"], "running")
        assert call(rt, "pd_draft_reply", fixture_id="priya-001",
                    job_token="wrong")["error"] == "permission_denied"
        assert call(rt, "pd_draft_reply", fixture_id="priya-002",
                    job_token="secret-token")["error"] == "permission_denied"
        assert call(rt, "pd_draft_reply", fixture_id="priya-001",
                    job_token="secret-token")["ok"] is True
    assert job_store.latest_draft(job["job_id"]) is not None
    assert not (locks / "active-job.json").exists()
    assert call(rt, "pd_draft_reply", fixture_id="priya-001",
                job_token="secret-token")["error"] == "permission_denied"


def test_pre_tool_call_blocks_ungranted_tools_for_bound_profiles(root, db):
    hook = make_pre_tool_call(runtime(root, db, "pd-noah"))
    assert hook(tool_name="pd_read_fixture", args={}) is None
    blocked = hook(tool_name="terminal", args={"command": "ls"})
    assert blocked["action"] == "block"
    assert make_pre_tool_call(runtime(root, db, "default"))(tool_name="terminal") is None
    extra = make_pre_tool_call(runtime(root, db, "pd-noah", extra_allowed_tools=["clarify"]))
    assert extra(tool_name="clarify") is None
