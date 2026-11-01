"""Sidecar contract: token-v1, GET only, loopback, read-only DB, one persona per sidecar."""

from __future__ import annotations

import http.client
import json
import sys
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "sidecar"))
sys.path.insert(0, str(HERE.parents[1] / "personal-agent-multilora"))

from hermes_plugin.store import open_store  # noqa: E402
from personadesk_sidecar import (  # noqa: E402
    SidecarConfig,
    TOKEN_HEADER,
    make_server,
    resolve_token_file,
)

TOKEN = "t" * 32
PRIYA = "priya-raman-support"
DANIEL = "daniel-okafor-cfo"


def _job(store, client_id, fixture_id, profile, draft=True):
    job, _ = store.create_job(
        source_key=f"{client_id}:{fixture_id}", principal="test", client_id=client_id,
        profile=profile, fixture_id=fixture_id, task="draft_reply", release_id=None,
    )
    if draft:
        store.transition(job["job_id"], "running")
        store.save_draft(
            job_id=job["job_id"], client_id=client_id, body=f"Draft for {fixture_id}",
            evidence=[{"kind": "fixture", "source_id": f"fixture:{fixture_id}", "fixture_id": fixture_id}],
            uncertainties=[], blocked_actions=["send_email"], writer={"name": "test"},
        )
        store.transition(job["job_id"], "awaiting_review")
    return job["job_id"]


@pytest.fixture()
def state(tmp_path):
    db = tmp_path / "personadesk.sqlite"
    store = open_store(db)
    ids = {
        "priya_review": _job(store, PRIYA, "priya-001", "pd-priya"),
        "priya_queued": _job(store, PRIYA, "priya-002", "pd-priya", draft=False),
        "daniel_review": _job(store, DANIEL, "daniel-001", "pd-daniel"),
    }
    store.conn.close()
    return db, ids


@pytest.fixture()
def sidecar(tmp_path, state):
    db, ids = state
    token_file = tmp_path / "webui" / "sidecar-auth" / "personadesk.token"
    token_file.parent.mkdir(parents=True)
    token_file.write_text(TOKEN, encoding="utf-8")
    server = make_server(SidecarConfig(persona=PRIYA, state_db=db, token_file=token_file), port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, ids, token_file, db
    server.shutdown()
    server.server_close()


def call(server, path, method="GET", token=TOKEN, want_headers=False):
    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
    headers = {TOKEN_HEADER: token} if token is not None else {}
    conn.request(method, path, headers=headers)
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    result = (resp.status, (json.loads(body) if body else None))
    return (*result, resp.headers) if want_headers else result


def test_binds_to_loopback_only(sidecar):
    server, *_ = sidecar
    assert server.server_address[0] == "127.0.0.1"


def test_health_needs_no_token(sidecar):
    server, *_ = sidecar
    status, body, headers = call(server, "/health", token=None, want_headers=True)
    assert (status, body) == (200, {"ok": True, "extension": "personadesk"})
    assert headers["Access-Control-Allow-Origin"] == "*"
    _, _, data_headers = call(server, "/v1/queue", want_headers=True)
    assert data_headers["Access-Control-Allow-Origin"] is None
    assert data_headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("token", [None, "", "wrong-token-wrong-token", TOKEN + "x"])
def test_missing_or_wrong_token_is_401(sidecar, token):
    server, *_ = sidecar
    assert call(server, "/v1/queue", token=token)[0] == 401


def test_absent_token_file_is_503(sidecar):
    server, _, token_file, _ = sidecar
    token_file.unlink()
    assert call(server, "/v1/queue")[0] == 503


def test_token_rotation_is_picked_up(sidecar):
    server, _, token_file, _ = sidecar
    token_file.write_text("r" * 32, encoding="utf-8")
    assert call(server, "/v1/queue")[0] == 401
    assert call(server, "/v1/queue", token="r" * 32)[0] == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_only_get_is_allowed(sidecar, method):
    server, *_ = sidecar
    assert call(server, "/v1/queue", method=method)[0] == 405


def test_queue_is_scoped_to_persona(sidecar):
    server, ids, *_ = sidecar
    status, body = call(server, "/v1/queue")
    assert status == 200 and body["persona"] == PRIYA
    assert {j["job_id"] for j in body["jobs"]} == {ids["priya_review"], ids["priya_queued"]}


def test_drafts_only_awaiting_review_for_persona(sidecar):
    server, ids, *_ = sidecar
    status, body = call(server, "/v1/drafts")
    assert status == 200
    assert [d["job_id"] for d in body["drafts"]] == [ids["priya_review"]]
    assert body["drafts"][0]["blocked_actions"] == ["send_email"]


def test_evidence_of_another_persona_is_not_found(sidecar):
    server, ids, *_ = sidecar
    status, body = call(server, f"/v1/evidence?job_id={ids['priya_review']}")
    assert status == 200 and body["evidence"][0]["fixture_id"] == "priya-001"
    assert call(server, f"/v1/evidence?job_id={ids['daniel_review']}")[0] == 404
    assert call(server, "/v1/evidence?job_id=../../etc")[0] == 404
    _, all_evidence = call(server, "/v1/evidence")
    assert {e["fixture_id"] for e in all_evidence["evidence"]} == {"priya-001"}


def test_layout_marks_planned_panels_unavailable(sidecar):
    server, *_ = sidecar
    status, body = call(server, "/v1/layout")
    assert status == 200
    panels = {p["id"]: p for p in body["layout"]["panels"]}
    assert panels["work-queue"] == {"id": "work-queue", "title": "Work queue", "available": True,
                                    "route": "/v1/queue"}
    assert panels["checklist"]["available"] is False and "phase" in panels["checklist"]["reason"]


def test_unknown_route_is_404(sidecar):
    server, *_ = sidecar
    assert call(server, "/v1/approve")[0] == 404


def test_database_is_opened_read_only(sidecar):
    server, ids, _, db = sidecar
    before = db.read_bytes()
    for path in ("/v1/queue", "/v1/drafts", "/v1/evidence", "/v1/layout"):
        assert call(server, path)[0] == 200
    assert db.read_bytes() == before


def test_missing_database_is_503(tmp_path):
    token_file = tmp_path / "t.token"
    token_file.write_text(TOKEN, encoding="utf-8")
    server = make_server(SidecarConfig(PRIYA, tmp_path / "absent.sqlite", token_file), port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert call(server, "/v1/queue")[0] == 503
        assert not (tmp_path / "absent.sqlite").exists()
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_persona_fails_fast(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_server(SidecarConfig("nobody-here", None, tmp_path / "t"), port=0)


def test_token_file_lookup_order(tmp_path):
    explicit = tmp_path / "x.token"
    assert resolve_token_file({"HERMES_EXT_SIDECAR_TOKEN_FILE": str(explicit),
                               "HERMES_WEBUI_STATE_DIR": "s", "HERMES_HOME": "h"}) == explicit
    assert resolve_token_file({"HERMES_WEBUI_STATE_DIR": str(tmp_path), "HERMES_HOME": "h"}) == (
        tmp_path / "sidecar-auth" / "personadesk.token")
    assert resolve_token_file({"HERMES_HOME": str(tmp_path)}) == (
        tmp_path / "webui" / "sidecar-auth" / "personadesk.token")
