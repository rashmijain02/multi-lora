"""PersonaDesk ``mail_*`` tools against the JMAP playground: identity, allowlists, bounds, drafts.

No LLM is involved. These qualify the tool layer and the in-repo JMAP subset, not a real
Stalwart server.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests
from conftest import runtime

from hermes_plugin import mail_tools, register
from hermes_plugin.mail_tools import TAG_VOCABULARY, TOOL_NAMES
from hermes_plugin.permissions import load_permissions
from hermes_plugin.store import open_store
from hermes_plugin.tasks import job_binding, locks_dir
from hermes_plugin.tools import make_handlers, make_pre_tool_call
from mailsim import jmap_seed
from mailsim.jmap_client import JmapClient
from mailsim.jmap_seed import ATTACHMENT_DATA

PRIYA = "priya-raman-support"
DANIEL = "daniel-okafor-cfo"


class Tools:
    """The handlers Hermes would call, bound to one persona profile."""

    def __init__(self, root, db, jmap, profile="pd-priya", **settings):
        self.rt = runtime(root, db, profile, mail_url=jmap[1].base_url, **settings)
        self.handlers = make_handlers(self.rt)

    def raw(self, tool: str, **args) -> str:
        return self.handlers[tool](args)

    def __call__(self, tool: str, **args) -> dict:
        return json.loads(self.raw(tool, **args))


@pytest.fixture
def tools(root, db, jmap, seeded):
    return Tools(root, db, jmap)


def fixture_id_of(email_id, mapping):
    return {v: k for k, v in mapping.items()}[email_id]


def search_all(tools: Tools, mapping, **filters) -> list[str]:
    """Walk every page via next_position; return fixture IDs in result order."""
    found, position = [], 0
    while position is not None:
        page = tools("mail_search", position=position, limit=20, **filters)
        assert page["ok"], page
        found += [fixture_id_of(m["id"], mapping) for m in page["messages"]]
        position = page["next_position"]
    return found


# ---- gating and identity --------------------------------------------------------------------
def test_tools_are_off_without_a_mail_url(root, db):
    handlers = make_handlers(runtime(root, db, "pd-priya"))
    result = json.loads(handlers["mail_search"]({}))
    assert result["ok"] is False and result["error"] == "mail_disabled"


def test_unbound_and_disabled_profiles_are_denied(root, db, jmap):
    for profile in ("default", "pd-maya", None):
        result = Tools(root, db, jmap, profile)("mail_search")
        assert result["error"] == "permission_denied", profile


def test_mail_url_must_be_loopback(root, db):
    rt = runtime(root, db, "pd-priya", mail_url="http://mail.example.com:8088")
    result = json.loads(make_handlers(rt)["mail_search"]({}))
    assert result["error"] == "invalid_request" and "loopback" in result["message"]


def test_unreachable_server_is_a_visible_failure(root, db):
    rt = runtime(root, db, "pd-priya", mail_url="http://127.0.0.1:1")
    result = json.loads(make_handlers(rt)["mail_search"]({}))
    assert result["ok"] is False and result["error"] == "mail_unavailable"


def test_the_model_cannot_choose_the_account_or_call_jmap(tools):
    for extra in ({"account": "daniel.okafor@company.example"}, {"persona": DANIEL},
                  {"accountId": "x"}, {"method": "EmailSubmission/set"}, {"password": "x"}):
        result = tools("mail_search", **extra)
        assert result["error"] == "invalid_request" and "Unknown argument" in result["message"]


def test_tool_set_cannot_send_and_is_declared_closed():
    assert set(mail_tools.SCHEMAS) == set(TOOL_NAMES) and len(TOOL_NAMES) == 7
    assert not any("send" in name or "submit" in name for name in TOOL_NAMES)
    for schema in mail_tools.SCHEMAS.values():
        assert schema["parameters"]["additionalProperties"] is False
        assert not {"account", "persona", "password", "url", "path"} & set(
            schema["parameters"]["properties"])
    assert mail_tools.FIXTURE_DOMAIN == "@" + jmap_seed.DOMAIN


def test_grants_and_guard_cover_the_mail_tools(root, db):
    permissions = load_permissions(root)
    for client_id in (PRIYA, DANIEL, "noah-williams-assistant"):
        assert set(TOOL_NAMES) <= set(permissions.personas[client_id].tools)
    hook = make_pre_tool_call(runtime(root, db, "pd-priya"))
    assert hook(tool_name="mail_search", args={}) is None
    assert hook(tool_name="mail_send", args={})["action"] == "block"
    assert hook(tool_name="EmailSubmission/set", args={})["action"] == "block"


def test_plugin_registers_mail_tools_only_when_configured(root, monkeypatch):
    class Ctx:
        profile_name = "pd-priya"

        def __init__(self, **settings):
            self.settings, self.tools = settings, {}

        def get_config(self, key, default=None):
            return {"workshop_root": str(root), "writer_backend": "template",
                    **self.settings}.get(key, default)

        def register_tool(self, name, **_kw):
            self.tools[name] = _kw

        def register_hook(self, *_a): ...
        def register_cli_command(self, **_kw): ...

    off, on = Ctx(), Ctx(mail_url="http://127.0.0.1:8088")
    register(off)
    register(on)
    assert not set(TOOL_NAMES) & set(off.tools) and len(off.tools) == 5
    assert set(TOOL_NAMES) <= set(on.tools) and len(on.tools) == 12


# ---- reading --------------------------------------------------------------------------------
def test_search_by_tag_matches_the_manifest(tools, seeded):
    _, pack, mapping = seeded[PRIYA]
    for tag in TAG_VOCABULARY:
        found = search_all(tools, mapping, tag=tag)
        assert len(found) == len(set(found))
        assert set(found) == {f.fixture_id for f in pack if tag in f.expected_tags}, tag


def test_pages_stay_under_the_output_cap_and_cover_everything_once(tools, seeded):
    _, pack, mapping = seeded[PRIYA]
    cap, position, seen, pages = tools.rt.permissions.max_tool_output_chars, 0, [], 0
    while position is not None:
        raw = tools.raw("mail_search", position=position, limit=20)
        assert len(raw) <= cap and '"truncated"' not in raw
        page = json.loads(raw)
        assert page["total"] == 30 and page["position"] == position
        seen += [fixture_id_of(m["id"], mapping) for m in page["messages"]]
        position, pages = page["next_position"], pages + 1
    assert pages > 1  # twenty summaries do not fit the cap, so the tool paged for the model
    assert len(seen) == len(set(seen)) == 30 and set(seen) == {f.fixture_id for f in pack}


def test_search_filters(tools, seeded):
    _, pack, mapping = seeded[PRIYA]
    by_id = {f.fixture_id: f for f in pack}
    assert search_all(tools, mapping, text=by_id["mb-priya-s05"].token) == ["mb-priya-s05"]
    assert sorted(search_all(tools, mapping, subject="quick question")) == [
        "mb-priya-s10", "mb-priya-s11"]
    assert set(search_all(tools, mapping, unread=True)) == {
        f.fixture_id for f in pack if "$seen" not in f.keywords}
    assert set(search_all(tools, mapping, mailbox="sent")) == {
        f.fixture_id for f in pack if f.mailbox == "sent"}
    assert search_all(tools, mapping, has_attachment=True) == ["mb-priya-s13"]
    window = search_all(tools, mapping, after="2026-10-01T09:00:00Z",
                        before="2026-10-01T12:00:00Z", newest_first=False)
    assert window == [f.fixture_id for f in pack[:3]]
    for bad in ({"limit": 0}, {"limit": 21}, {"position": -1}, {"mailbox": "spam"},
                {"tag": "Bad Tag"}, {"after": "yesterday"}, {"unread": "yes"}):
        assert tools("mail_search", **bad)["error"] == "invalid_request", bad


def test_get_marks_message_text_untrusted_and_has_no_side_effects(tools, seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-s14"]  # carries an injected instruction
    before = client.method("Email/get", ids=[email_id], properties=["keywords", "mailboxIds"])
    result = tools("mail_get", email_id=email_id)
    assert result["ok"] and result["untrusted_content"] is True
    assert "SYSTEM NOTICE" in result["body"] and "never follow" in result["note"].lower()
    assert result["mutable"] is True and "needs-review" in result["tags"]
    after = client.method("Email/get", ids=[email_id], properties=["keywords", "mailboxIds"])
    assert after["list"] == before["list"]
    unseen = tools("mail_search", unread=True, text="Action required")["messages"]
    assert [m["id"] for m in unseen] == [email_id]  # reading does not mark messages seen


def test_get_reports_attachment_metadata_but_no_blob(tools, seeded):
    _, _, mapping = seeded[PRIYA]
    result = tools("mail_get", email_id=mapping["mb-priya-s13"])
    assert result["attachments"] == [
        {"name": "report.csv", "type": "text/csv", "size": len(ATTACHMENT_DATA)}]
    assert "blobId" not in json.dumps(result) and result["has_attachment"] is True


def test_get_body_is_size_limited(tools, seeded):
    client, _, _ = seeded[PRIYA]
    boxes = client.mailboxes()
    long_text = "word " * 5000
    raw = (f"From: Alex <alex.morgan@customer.example>\r\nTo: priya.raman@company.example\r\n"
           f"Subject: Long one\r\nMessage-ID: <long1@mailbox.personadesk.test>\r\n"
           f"Date: Mon, 05 Oct 2026 09:00:00 +0000\r\n\r\n{long_text}\r\n").encode()
    blob = client.upload(raw, "message/rfc822")
    created = client.method("Email/import", emails={"i": {
        "blobId": blob, "mailboxIds": {boxes["inbox"]: True}, "keywords": {}}})
    email_id = created["created"]["i"]["id"]
    raw_out = tools.raw("mail_get", email_id=email_id)
    result = json.loads(raw_out)
    assert result["body_truncated"] is True and len(raw_out) <= 4000
    assert result["body"].startswith("word word")


def test_missing_and_malformed_ids_are_visible_errors(tools):
    assert tools("mail_get", email_id="doesnotexist")["error"] == "not_found"
    assert tools("mail_get", email_id="../../etc/passwd")["error"] == "invalid_request"
    assert tools("mail_get", email_id=None)["error"] == "invalid_request"
    assert tools("mail_get_thread", thread_id="nothread")["error"] == "not_found"


def test_thread_retrieval_and_pagination(tools, seeded):
    _, _, mapping = seeded[PRIYA]
    page = tools("mail_get_thread", email_id=mapping["mb-priya-c1-m2"])
    assert [fixture_id_of(m["id"], mapping) for m in page["messages"]] == [
        "mb-priya-c1-m1", "mb-priya-c1-m2", "mb-priya-c1-m3"]
    assert page["total"] == 3 and page["next_position"] is None and page["untrusted_content"]
    first = tools("mail_get_thread", thread_id=page["thread_id"], limit=2)
    assert first["count"] == 2 and first["next_position"] == 2
    rest = tools("mail_get_thread", thread_id=page["thread_id"], position=2, limit=2)
    assert [fixture_id_of(m["id"], mapping) for m in rest["messages"]] == ["mb-priya-c1-m3"]
    same = tools("mail_get_thread", email_id=mapping["mb-priya-s10"])
    assert same["total"] == 1  # the same-subject message is not part of another thread
    for args in ({}, {"thread_id": "a", "email_id": "b"}):
        assert tools("mail_get_thread", **args)["error"] == "invalid_request"


# ---- isolation ------------------------------------------------------------------------------
def test_another_personas_messages_are_not_reachable(tools, seeded):
    daniel_client, _, daniel_map = seeded[DANIEL]
    foreign = daniel_map["mb-daniel-c1-m1"]
    before = daniel_client.method("Email/get", ids=[foreign], properties=["keywords"])
    assert tools("mail_get", email_id=foreign)["error"] == "not_found"
    thread = before and daniel_client.method(
        "Email/get", ids=[foreign], properties=["threadId"])["list"][0]["threadId"]
    assert tools("mail_get_thread", thread_id=thread)["error"] == "not_found"
    for result in (tools("mail_update_tags", email_ids=[foreign], add=["follow-up"]),
                   tools("mail_set_read", email_ids=[foreign], read=False),
                   tools("mail_move", email_ids=[foreign], target="trash")):
        assert result["ok"] is False and result["failed"] == {foreign: "not_found"}
    assert daniel_client.method("Email/get", ids=[foreign], properties=["keywords"]) == before


# ---- writes ---------------------------------------------------------------------------------
def keywords(client, email_id) -> dict:
    return client.method("Email/get", ids=[email_id], properties=["keywords"])["list"][0][
        "keywords"]


def test_tag_update_changes_only_named_tags(tools, seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-c1-m1"]
    before = keywords(client, email_id)
    result = tools("mail_update_tags", email_ids=[email_id], add=["follow-up", "needs-review"])
    assert result["ok"] and result["updated"] == [email_id]
    assert tools("mail_update_tags", email_ids=[email_id], remove=["follow-up"])["ok"]
    after = keywords(client, email_id)
    assert set(after) == set(before) | {"needs-review"} and "$seen" in after


def test_tag_vocabulary_and_arguments_are_validated(tools, seeded):
    email_id = seeded[PRIYA][2]["mb-priya-c1-m1"]
    for args in ({"add": ["$seen"]}, {"add": ["bogus"]}, {"add": ["follow-up"],
                                                          "remove": ["follow-up"]},
                 {}, {"add": "follow-up"}, {"add": ["$draft"]}, {"remove": ["keywords/x"]}):
        result = tools("mail_update_tags", email_ids=[email_id], **args)
        assert result["error"] == "invalid_request", args
    assert tools("mail_update_tags", email_ids=[], add=["follow-up"])["error"] == "invalid_request"
    too_many = [f"id{i}" for i in range(21)]
    assert tools("mail_update_tags", email_ids=too_many,
                 add=["follow-up"])["error"] == "invalid_request"
    assert tools("mail_update_tags", email_ids=[email_id, email_id],
                 add=["follow-up"])["error"] == "invalid_request"


def test_partial_updates_are_reported_not_hidden(tools, seeded):
    client, _, mapping = seeded[PRIYA]
    good = [mapping["mb-priya-c2-m1"], mapping["mb-priya-c2-m2"]]
    result = tools("mail_update_tags", email_ids=[*good, "ghost"], add=["follow-up"])
    assert result["ok"] is False and result["error"] == "partial_failure"
    assert sorted(result["updated"]) == sorted(good) and result["failed"] == {"ghost": "not_found"}
    assert all("follow-up" in keywords(client, i) for i in good)
    assert "follow-up" not in keywords(client, mapping["mb-priya-c1-m1"])
    none = tools("mail_update_tags", email_ids=["ghost"], add=["follow-up"])
    assert none["error"] == "update_failed" and none["updated"] == []


def test_only_fixture_owned_messages_can_be_changed(tools, seeded):
    client, _, _ = seeded[PRIYA]
    boxes = client.mailboxes()
    made = client.method("Email/set", create={"d": {
        "mailboxIds": {boxes["drafts"]: True}, "keywords": {"$draft": True},
        "to": [{"email": "alex.morgan@customer.example"}], "subject": "hand made",
        "bodyValues": {"1": {"value": "x"}}, "textBody": [{"partId": "1"}]}})
    draft_id = made["created"]["d"]["id"]
    for result in (tools("mail_update_tags", email_ids=[draft_id], add=["follow-up"]),
                   tools("mail_set_read", email_ids=[draft_id], read=False),
                   tools("mail_move", email_ids=[draft_id], target="trash")):
        assert result["ok"] is False and result["failed"] == {draft_id: "not_permitted"}
    assert keywords(client, draft_id) == {"$draft": True}
    assert tools("mail_get", email_id=draft_id)["mutable"] is False


def test_stale_state_blocks_a_change_until_reread(tools, seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-s04"]
    seen_state = tools("mail_get", email_id=email_id)["state"]
    client.method("Email/set", update={email_id: {"keywords/waiting-on-customer": True}})
    stale = tools("mail_update_tags", email_ids=[email_id], add=["needs-review"],
                  if_state=seen_state)
    assert stale["ok"] is False and stale["error"] == "stale_state"
    assert "needs-review" not in keywords(client, email_id)
    fresh = tools("mail_get", email_id=email_id)["state"]
    assert tools("mail_update_tags", email_ids=[email_id], add=["needs-review"],
                 if_state=fresh)["ok"]
    assert {"needs-review", "waiting-on-customer"} <= set(keywords(client, email_id))
    assert tools("mail_update_tags", email_ids=[email_id], add=["follow-up"],
                 if_state="bad state!")["error"] == "invalid_request"


def test_set_read_toggles_only_seen(tools, seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-c1-m3"]  # unread and tagged
    before = keywords(client, email_id)
    assert "$seen" not in before
    assert tools("mail_set_read", email_ids=[email_id], read=True)["ok"]
    assert keywords(client, email_id) == {**before, "$seen": True}
    assert tools("mail_set_read", email_ids=[email_id], read=False)["ok"]
    assert keywords(client, email_id) == before
    assert tools("mail_set_read", email_ids=[email_id], read="yes")["error"] == "invalid_request"
    assert tools("mail_set_read", email_ids=[email_id])["error"] == "invalid_request"


def test_move_replaces_membership_and_keeps_content(tools, seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-s03"]
    boxes = client.mailboxes()
    props = ["keywords", "preview", "subject"]
    before = client.method("Email/get", ids=[email_id], properties=props)["list"]
    inbox_total = tools("mail_search", mailbox="inbox")["total"]
    result = tools("mail_move", email_ids=[email_id], target="archive")
    assert result["ok"] and result["target"] == "archive" and "replaced" in result["membership"]
    moved = client.method("Email/get", ids=[email_id], properties=[*props, "mailboxIds"])
    assert moved["list"][0].pop("mailboxIds") == {boxes["archive"]: True}
    assert moved["list"] == before
    assert tools("mail_search", mailbox="archive")["total"] == 1
    assert tools("mail_search", mailbox="inbox")["total"] == inbox_total - 1
    assert tools("mail_move", email_ids=[email_id], target="inbox")["ok"]
    assert tools("mail_search", mailbox="inbox")["total"] == inbox_total
    for target in ("drafts", "sent", "nowhere", None):
        assert tools("mail_move", email_ids=[email_id], target=target)["error"] == \
            "invalid_request"


# ---- drafts ---------------------------------------------------------------------------------
def drafts(client) -> list[dict]:
    ids = client.query_all({"inMailbox": client.mailboxes()["drafts"]})
    if not ids:
        return []
    return client.method("Email/get", ids=ids, fetchTextBodyValues=True, properties=[
        "id", "to", "subject", "keywords", "inReplyTo", "threadId", "bodyValues",
        "header:X-PersonaDesk-Job:asText", "header:X-PersonaDesk-Artifact-Hash:asText",
        "header:X-PersonaDesk-Revision:asText"])["list"]


def test_save_draft_projects_the_reviewed_artifact_and_is_retry_safe(
        root, db, jmap, seeded, tmp_path):
    client, _, mapping = seeded[PRIYA]
    tools = Tools(root, db, jmap)
    store = open_store(tmp_path / "job-owner.db")
    job, _ = store.create_job(source_key="k", principal="op", client_id=PRIYA, profile="pd-priya",
                              fixture_id="priya-001", task="draft_reply", release_id=None)
    job_id = job["job_id"]
    store.transition(job_id, "running")
    locks = locks_dir(root)
    locks.mkdir(parents=True, exist_ok=True)
    source = mapping["mb-priya-c1-m3"]
    def stored_body(item):  # the wire form of a stored message uses CRLF line endings
        return item["bodyValues"]["1"]["value"].replace("\r\n", "\n").rstrip("\n")

    sent_before = tools("mail_search", mailbox="sent")["total"]

    def save(**over):
        return tools("mail_save_draft", job_token="tok", source_email_id=source, **over)

    with job_binding(locks, job_id, "tok", store.path):
        assert tools("mail_save_draft", job_token="wrong",
                     source_email_id=source)["error"] == "permission_denied"
        assert save()["error"] == "invalid_request"  # no stored draft yet
        first_ledger = store.save_draft(
            job_id=job_id, client_id=PRIYA, body="Hello,\n\nWe are on it.", evidence=[],
            uncertainties=[], blocked_actions=["send_email"], writer={"backend": "template"})
        own = tools("mail_save_draft", job_token="tok", source_email_id=mapping["mb-priya-c1-m2"])
        assert own["error"] == "invalid_request"  # that message is Priya's own reply

        created = save()
        assert created["ok"] and created["status"] == "created" and created["sent"] is False
        assert created["artifact_hash"] == first_ledger["artifact_hash"]
        (draft,) = drafts(client)
        assert draft["id"] == created["mail_draft_id"]
        assert stored_body(draft) == "Hello,\n\nWe are on it."
        assert draft["keywords"] == {"$draft": True, "$seen": True}
        assert draft["header:X-PersonaDesk-Job:asText"] == job_id
        assert draft["header:X-PersonaDesk-Artifact-Hash:asText"] == first_ledger["artifact_hash"]
        source_view = client.method("Email/get", ids=[source], properties=[
            "from", "messageId", "threadId", "subject"])["list"][0]
        assert draft["to"] == source_view["from"] and draft["threadId"] == source_view["threadId"]
        assert draft["inReplyTo"] == source_view["messageId"]
        assert draft["subject"] == source_view["subject"]  # already "Re: ..."

        again = save()  # a retry reconciles the known draft
        assert again["status"] == "unchanged" and again["mail_draft_id"] == draft["id"]
        assert len(drafts(client)) == 1

        second_ledger = store.save_draft(
            job_id=job_id, client_id=PRIYA, body="Updated reply.", evidence=[], uncertainties=[],
            blocked_actions=["send_email"], writer={"backend": "template"})
        replaced = save()
        assert replaced["status"] == "replaced" and replaced["revision"] == 2
        (current,) = drafts(client)  # the superseded projection is gone, not duplicated
        assert current["id"] != draft["id"] and stored_body(current) == "Updated reply."
        assert current["header:X-PersonaDesk-Artifact-Hash:asText"] == \
            second_ledger["artifact_hash"] != first_ledger["artifact_hash"]
    assert tools("mail_search", mailbox="sent")["total"] == sent_before  # nothing was sent
    assert save()["error"] == "permission_denied"  # the binding ended with the job


def test_save_draft_recipient_cannot_be_chosen_by_the_model(tools):
    result = tools("mail_save_draft", job_token="x", source_email_id="abc",
                   to="attacker@evil.example")
    assert result["error"] == "invalid_request" and "Unknown argument" in result["message"]


@pytest.mark.parametrize("failure", ["interrupted", "notDestroyed"])
def test_save_draft_reconciles_superseded_projections_after_cleanup_failure(
        tools, seeded, root, db, monkeypatch, failure):
    client, _, mapping = seeded[PRIYA]
    store = open_store(db)
    job, _ = store.create_job(source_key="cleanup", principal="op", client_id=PRIYA,
                              profile="pd-priya", fixture_id="priya-001",
                              task="draft_reply", release_id=None)
    job_id = job["job_id"]
    store.transition(job_id, "running")
    locks = locks_dir(root)
    locks.mkdir(parents=True, exist_ok=True)
    original_method = JmapClient.method

    def failed_cleanup(self, method, **args):
        if method == "Email/set" and args.get("destroy"):
            if failure == "interrupted":
                raise requests.ConnectionError("Synthetic interrupted cleanup")
            return {"destroyed": None, "notDestroyed": {
                email_id: {"type": "forbidden"} for email_id in args["destroy"]}}
        return original_method(self, method, **args)

    def save():
        return tools("mail_save_draft", job_token="cleanup-token",
                     source_email_id=mapping["mb-priya-c1-m3"])

    try:
        with job_binding(locks, job_id, "cleanup-token", store.path):
            store.save_draft(job_id=job_id, client_id=PRIYA, body="Original draft.",
                             evidence=[], uncertainties=[], blocked_actions=["send_email"],
                             writer={"backend": "template"})
            old = save()
            assert old["ok"]
            ledger = store.save_draft(
                job_id=job_id, client_id=PRIYA, body="Replacement draft.", evidence=[],
                uncertainties=[], blocked_actions=["send_email"], writer={"backend": "template"})
            with monkeypatch.context() as patch:
                patch.setattr(JmapClient, "method", failed_cleanup)
                failed = save()
                assert failed["ok"] is False
                assert failed["error"] == (
                    "mail_unavailable" if failure == "interrupted" else "draft_cleanup_failed")
                assert len(drafts(client)) == 2
                assert save()["ok"] is False
            recovered = save()
            assert recovered["ok"]
            (current,) = drafts(client)
            assert current["id"] != old["mail_draft_id"]
            assert current["header:X-PersonaDesk-Artifact-Hash:asText"] == ledger["artifact_hash"]
            assert save()["status"] == "unchanged"
    finally:
        store.conn.close()

# ---- audit ----------------------------------------------------------------------------------
def test_audit_records_operations_without_bodies_or_credentials(tools, seeded, root):
    _, _, mapping = seeded[PRIYA]
    tools("mail_get", email_id=mapping["mb-priya-s14"])
    tools("mail_update_tags", email_ids=[mapping["mb-priya-c1-m1"], "ghost"], add=["follow-up"])
    tools("mail_get", email_id="doesnotexist")
    path = Path(root) / "artifacts" / "mail" / "audit.jsonl"
    text = path.read_text(encoding="utf-8")
    assert "SYSTEM NOTICE" not in text and "personadesk-local" not in text
    records = [json.loads(line) for line in text.splitlines()]
    assert [r["operation"] for r in records] == ["mail_get", "mail_update_tags", "mail_get"]
    assert [r["outcome"] for r in records] == ["ok", "partial_failure", "not_found"]
    assert {r["persona"] for r in records} == {PRIYA}
    assert records[1]["failed"] == {"ghost": "not_found"} and records[1]["state"]
