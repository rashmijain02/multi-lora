"""Job records, the state machine, review binding, and the bounded worker pipeline."""

from __future__ import annotations

import dataclasses
import json

import pytest
from conftest import FAKE_HERMES

from hermes_plugin.commands import main
from hermes_plugin.permissions import load_permissions
from hermes_plugin.store import InvalidTransition, open_store
from hermes_plugin.tasks import (
    WorkerFailed,
    build_worker_argv,
    global_lock,
    judge,
    locks_dir,
    parse_stream,
    reconcile,
    run_job,
)


def new_job(store, source_key="k1", fixture_id="priya-001"):
    return store.create_job(source_key=source_key, principal="op", client_id="priya-raman-support",
                            profile="pd-priya", fixture_id=fixture_id, task="draft_reply",
                            release_id=None)


def test_source_key_is_idempotent(db):
    store = open_store(db)
    job, created = new_job(store)
    again, created_again = new_job(store)
    assert created and not created_again and again["job_id"] == job["job_id"]
    with pytest.raises(ValueError, match="different request"):
        new_job(store, fixture_id="priya-002")


def test_state_machine_rejects_illegal_transitions(db):
    store = open_store(db)
    job, _ = new_job(store)
    with pytest.raises(InvalidTransition):
        store.transition(job["job_id"], "approved")
    store.transition(job["job_id"], "running")
    store.transition(job["job_id"], "failed", error="boom")
    assert store.transition(job["job_id"], "queued")["status"] == "queued"


def test_review_is_bound_to_latest_revision(db):
    store = open_store(db)
    job, _ = new_job(store)
    job_id = job["job_id"]
    store.transition(job_id, "running")
    first = store.save_draft(job_id=job_id, client_id="priya-raman-support", body="v1",
                             evidence=[], uncertainties=[], blocked_actions=[], writer={})
    second = store.save_draft(job_id=job_id, client_id="priya-raman-support", body="v2",
                              evidence=[], uncertainties=[], blocked_actions=[], writer={})
    assert first["artifact_hash"] != second["artifact_hash"]
    store.transition(job_id, "awaiting_review")
    with pytest.raises(InvalidTransition, match="hash mismatch"):
        store.record_review(job_id=job_id, reviewer="op", presented_hash=first["artifact_hash"],
                            decision="approve", edited_text=None, reason=None,
                            learning_consent=False)
    assert store.get_job(job_id)["status"] == "awaiting_review"
    assert store.reviews() == []
    store.record_review(job_id=job_id, reviewer="op", presented_hash=second["artifact_hash"],
                        decision="approve", edited_text=None, reason=None,
                        learning_consent=False)
    assert store.get_job(job_id)["status"] == "approved"
    with pytest.raises(InvalidTransition):  # a second decision is not possible
        store.record_review(job_id=job_id, reviewer="op",
                            presented_hash=second["artifact_hash"], decision="reject",
                            edited_text=None, reason=None, learning_consent=False)
    assert len(store.reviews()) == 1


def test_draft_for_other_persona_is_rejected(db):
    store = open_store(db)
    job, _ = new_job(store)
    store.transition(job["job_id"], "running")
    with pytest.raises(PermissionError):
        store.save_draft(job_id=job["job_id"], client_id="daniel-okafor-cfo", body="x",
                         evidence=[], uncertainties=[], blocked_actions=[], writer={})


def test_worker_argv_is_an_argument_array(tmp_path):
    argv = build_worker_argv("hermes", "pd-priya", tmp_path / "q.txt", 4)
    assert argv[1:] == ["-p", "pd-priya", "chat", "--oneshot", "--query-file",
                        str(tmp_path / "q.txt"), "--format", "stream-json",
                        "--toolsets", "personadesk", "--max-turns", "4"]


@pytest.mark.parametrize("lines, code, message", [
    ([], None, "timeout"),
    (['{"type":"system","session_id":"s"}'], 0, "no terminal result"),
    (['{"type":"result","exit_code":0,"error":"budget"}'], 0, "worker error"),
    (['{"type":"result","exit_code":1}'], 1, "nonzero exit"),
    (['{"type":"result","exit_code":0}'], 1, "nonzero exit"),
    (["not json", "[1]"], 0, "no terminal result"),
])
def test_judge_treats_incomplete_runs_as_failures(lines, code, message):
    with pytest.raises(WorkerFailed, match=message):
        judge(parse_stream(lines), code)


def test_parse_stream_collects_session_and_tools():
    outcome = parse_stream([
        '{"type":"system","subtype":"init","session_id":"s1"}',
        '{"type":"tool_use","name":"pd_read_fixture"}',
        '{"type":"result","session_id":"s1","exit_code":0,"text":"done"}',
    ])
    judge(outcome, 0)
    assert outcome.session_id == "s1" and outcome.tool_calls == ["pd_read_fixture"]


def cli(capsys, *args) -> tuple[int, dict]:
    code = main(["--profile", args[0], "--hermes-bin", FAKE_HERMES, *args[1:]])
    return code, json.loads(capsys.readouterr().out)


def test_end_to_end_run_show_review(root, db, capsys):
    code, out = cli(capsys, "pd-daniel", "--state-db", str(db), "run", "--fixture", "daniel-001")
    assert code == 0 and out["job"]["status"] == "awaiting_review"
    draft = out["draft"]
    assert "does not match PO" in draft["body"] and draft["writer"]["backend"] == "template"
    assert "approve_payment" in draft["blocked_actions"]
    job_id = out["job"]["job_id"]

    code, again = cli(capsys, "pd-daniel", "--state-db", str(db), "run", "--fixture",
                      "daniel-001")
    assert again["created"] is False and again["job"]["job_id"] == job_id

    code, out = cli(capsys, "pd-daniel", "--state-db", str(db), "review", job_id,
                    "--draft-hash", "sha256:wrong", "--decision", "approve")
    assert code == 2 and "hash mismatch" in out["message"]
    code, out = cli(capsys, "pd-daniel", "--state-db", str(db), "review", job_id,
                    "--draft-hash", draft["artifact_hash"], "--decision", "approve")
    assert code == 0 and out["job"]["status"] == "approved"


def test_other_profile_cannot_see_or_review_job(root, db, capsys):
    _, out = cli(capsys, "pd-daniel", "--state-db", str(db), "run", "--fixture", "daniel-003")
    job_id = out["job"]["job_id"]
    code, out = cli(capsys, "pd-priya", "--state-db", str(db), "show", job_id)
    assert code == 2 and "different persona" in out["message"]
    code, out = cli(capsys, "pd-priya", "--state-db", str(db), "review", job_id,
                    "--draft-hash", "x", "--decision", "approve")
    assert code == 2


def test_unlisted_operator_is_denied(root, db, capsys):
    (root / "config" / "operators.json").write_text('{"operators": {}}', encoding="utf-8")
    code, out = cli(capsys, "pd-priya", "--state-db", str(db), "status")
    assert code == 2 and out["error"] == "PermissionDenied"


def test_task_outside_grant_is_denied(root, db, capsys):
    code, out = cli(capsys, "pd-priya", "--state-db", str(db), "run", "--fixture", "priya-001",
                    "--task", "approval_packet")
    assert code == 2 and "not permitted" in out["message"]


@pytest.mark.parametrize("mode", ["no_result", "error", "nonzero", "no_draft", "malformed"])
def test_worker_failures_never_look_like_success(root, db, capsys, monkeypatch, mode):
    monkeypatch.setenv("FAKE_HERMES_MODE", mode)
    code, out = cli(capsys, "pd-noah", "--state-db", str(db), "run", "--fixture", "noah-002")
    assert code == 3 and out["job"]["status"] == "failed" and out["job"]["error"]


def test_retry_after_failure(root, db, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_HERMES_MODE", "error")
    _, out = cli(capsys, "pd-noah", "--state-db", str(db), "run", "--fixture", "noah-001")
    monkeypatch.setenv("FAKE_HERMES_MODE", "ok")
    code, out = cli(capsys, "pd-noah", "--state-db", str(db), "retry", out["job"]["job_id"])
    assert code == 0 and out["job"]["status"] == "awaiting_review" and out["job"]["attempts"] == 2
    assert out["job"]["error"] is None


def test_timeout_fails_the_job(root, db, monkeypatch):
    monkeypatch.setenv("FAKE_HERMES_MODE", "sleep")
    permissions = dataclasses.replace(load_permissions(root), worker_timeout_seconds=3)
    store = open_store(db)
    job, _ = new_job(store)
    result = run_job(store=store, job=job, grant=permissions.personas["priya-raman-support"],
                     permissions=permissions, hermes_bin=FAKE_HERMES, lock_dir=locks_dir(root))
    assert result["status"] == "failed" and result["error"].startswith("timeout")


def test_global_lock_serializes_jobs(tmp_path):
    held = global_lock(tmp_path)
    with held, pytest.raises(WorkerFailed, match="global lock"), global_lock(tmp_path):
        pass
    with global_lock(tmp_path):  # released afterwards
        pass


def test_reconcile_stale_running_job(db, tmp_path):
    store = open_store(db)
    job, _ = new_job(store)
    store.transition(job["job_id"], "running")
    assert reconcile(store, job["job_id"], tmp_path)["status"] == "failed"
    job2, _ = new_job(store, source_key="k2")
    store.transition(job2["job_id"], "running")
    store.save_draft(job_id=job2["job_id"], client_id="priya-raman-support", body="b",
                     evidence=[], uncertainties=[], blocked_actions=[], writer={})
    assert reconcile(store, job2["job_id"], tmp_path)["status"] == "awaiting_review"
