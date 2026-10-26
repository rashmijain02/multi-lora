"""Release promotion and rollback, feedback export filters, writer identity, registration."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import runtime

from hermes_plugin import register
from hermes_plugin.feedback import eligible_feedback
from hermes_plugin.releases import ReleaseError, active_release, create_candidate, promote, rollback
from hermes_plugin.store import open_store
from hermes_plugin.tools import SCHEMAS, TOOLSET
from hermes_plugin.writer import HttpWriter, WriterUnavailable

CLIENT = "priya-raman-support"


def candidate(root, name, passed=True, created_by="alice"):
    comp = root / "artifacts" / "candidates" / name
    comp.mkdir(parents=True)
    (comp / "memory.md").write_text(f"memory {name}", encoding="utf-8")
    (comp / "eval.json").write_text(json.dumps({"passed": passed}), encoding="utf-8")
    rel = f"artifacts/candidates/{name}"
    return create_candidate(
        root, client_id=CLIENT, created_by=created_by,
        components={"memory": {"path": f"{rel}/memory.md", "version": name}},
        evaluation_report=f"{rel}/eval.json", base={"model": "Qwen/Qwen3-8B"},
        policy_version="v1",
    )


def test_promote_requires_independent_approver_and_passing_eval(root):
    good = candidate(root, "c1")
    with pytest.raises(ReleaseError, match="own release"):
        promote(root, CLIENT, good["release_id"], "alice")
    bad = candidate(root, "c2", passed=False)
    with pytest.raises(ReleaseError, match="did not pass"):
        promote(root, CLIENT, bad["release_id"], "bob")
    assert active_release(root, CLIENT) is None
    assert promote(root, CLIENT, good["release_id"], "bob")["release_id"] == good["release_id"]


def test_tampered_component_or_report_blocks_promotion(root):
    rel = candidate(root, "c1")
    (root / "artifacts" / "candidates" / "c1" / "memory.md").write_text("edited", "utf-8")
    with pytest.raises(ReleaseError, match="checksum"):
        promote(root, CLIENT, rel["release_id"], "bob")
    rel2 = candidate(root, "c2")
    (root / "artifacts" / "candidates" / "c2" / "eval.json").write_text('{"passed": true} ',
                                                                         "utf-8")
    with pytest.raises(ReleaseError, match="changed"):
        promote(root, CLIENT, rel2["release_id"], "bob")


def test_rollback_restores_previous_release(root):
    first, second = candidate(root, "c1"), candidate(root, "c2")
    promote(root, CLIENT, first["release_id"], "bob")
    promote(root, CLIENT, second["release_id"], "bob")
    assert rollback(root, CLIENT, "bob")["release_id"] == first["release_id"]


def test_feedback_export_respects_consent_split_and_rejections(root, db):
    store = open_store(db)
    grant = runtime(root, db, "pd-priya").grant()

    def reviewed(key, fixture, decision, consent, edited=None):
        job, _ = store.create_job(source_key=key, principal="op", client_id=CLIENT,
                                  profile="pd-priya", fixture_id=fixture, task="draft_reply",
                                  release_id=None)
        store.transition(job["job_id"], "running")
        draft = store.save_draft(job_id=job["job_id"], client_id=CLIENT, body="draft",
                                 evidence=[], uncertainties=[], blocked_actions=[], writer={})
        store.transition(job["job_id"], "awaiting_review")
        store.record_review(job_id=job["job_id"], reviewer="op",
                            presented_hash=draft["artifact_hash"], decision=decision,
                            edited_text=edited, reason=None, learning_consent=consent)

    reviewed("a", "priya-001", "approve", True)                 # dev split -> exported
    reviewed("b", "priya-001", "approve", False)                # no consent
    reviewed("c", "priya-001", "reject", True)                  # rejected, no edit
    reviewed("d", "priya-001", "reject", True, edited="Better") # edit is the target
    reviewed("e", "priya-003", "approve", True)                 # held-out split
    rows, skipped = eligible_feedback(store, root, grant)
    assert [r["target"] for r in rows] == ["draft", "Better"]
    assert sorted(s["reason"] for s in skipped) == \
        ["held_out_split", "no_learning_consent", "rejected_without_edit"]


@pytest.fixture
def writer_server():
    reply = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", reply
    server.shutdown()


def test_http_writer_rejects_wrong_adapter_or_empty_text(writer_server):
    url, reply = writer_server
    writer = HttpWriter(base_url=url, timeout=5)
    args = {"client_id": CLIENT, "adapter": "priya", "subject": "s", "body": "b", "brief": []}
    reply.update(client_id=CLIENT, adapter="daniel", text="hi")
    with pytest.raises(WriterUnavailable, match="different persona"):
        writer.generate(**args)
    reply.update(adapter="priya", text="  ")
    with pytest.raises(WriterUnavailable, match="empty"):
        writer.generate(**args)
    reply.update(text="Hello", base_model="Qwen/Qwen3-8B", adapted=True)
    text, identity = writer.generate(**args)
    assert text == "Hello" and identity["adapter"] == "priya" and identity["adapted"]


def test_unreachable_writer_is_unavailable():
    with pytest.raises(WriterUnavailable):
        HttpWriter(base_url="http://127.0.0.1:9", timeout=2).generate(
            client_id=CLIENT, adapter="priya", subject="s", body="b", brief=[])


class FakeCtx:
    profile_name = "pd-priya"

    def __init__(self, settings):
        self.settings, self.tools, self.hooks, self.commands = settings, {}, {}, {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_tool(self, *, name, toolset, schema, handler):
        self.tools[name] = (toolset, schema, handler)

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_cli_command(self, *, name, help, setup_fn, handler_fn):
        self.commands[name] = (setup_fn, handler_fn)


def test_register_wires_tools_hook_and_command(root, db):
    ctx = FakeCtx({"workshop_root": str(root), "writer_backend": "template"})
    register(ctx)
    assert set(ctx.tools) == set(SCHEMAS)
    assert {toolset for toolset, _, _ in ctx.tools.values()} == {TOOLSET}
    assert ctx.hooks["pre_tool_call"](tool_name="terminal")["action"] == "block"
    out = json.loads(ctx.tools["pd_read_fixture"][2]({"fixture_id": "priya-001"}))
    assert out["ok"] and out["fixture"]["id"] == "priya-001"
    assert "personadesk" in ctx.commands
