"""Protocol harness for the JMAP playground (proposal §7 gates), with no LLM involved.

These run against ``mailsim.jmap.JmapServer``, the in-repo JMAP subset. They qualify that
simulator, not Stalwart: nothing here has been run against a real Stalwart release.
"""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from email import message_from_bytes, policy
from pathlib import Path

import pytest
import requests
from conftest import client_for

from mailsim import cli
from mailsim.jmap import JmapApi, JmapServer
from mailsim.jmap_client import JmapClient, JmapError
from mailsim.jmap_seed import ATTACHMENT_DATA, PERSONAS, build_all, build_pack, manifest, seed

PRIYA = "priya-raman-support"
DANIEL = "daniel-okafor-cfo"
NOAH = "noah-williams-assistant"


def fixture_ids(client: JmapClient, ids: list[str], mapping: dict[str, str]) -> set[str]:
    reverse = {email_id: fid for fid, email_id in mapping.items()}
    return {reverse[i] for i in ids}


def get(client: JmapClient, email_id: str, *props: str) -> dict:
    result = client.method("Email/get", ids=[email_id], properties=list(props))
    assert not result["notFound"], result
    return result["list"][0]


def test_fresh_seed_maps_every_fixture(seeded):
    assert sum(len(m) for _, _, m in seeded.values()) == 90
    for client, pack, mapping in seeded.values():
        assert client.method("Email/query", calculateTotal=True, limit=1)["total"] == 30
        assert set(mapping) == {f.fixture_id for f in pack}
    assert len(manifest()["fixtures"]) == 90


def test_pack_is_byte_reproducible():
    assert [f.sha256 for f in build_pack(PRIYA)] == [f.sha256 for f in build_pack(PRIYA)]
    ids = [f.fixture_id for pack in build_all().values() for f in pack]
    assert len(ids) == len(set(ids)) == 90
    tokens = [f.token for pack in build_all().values() for f in pack]
    assert len(tokens) == len(set(tokens))


def test_seed_replay_adds_no_duplicates(seeded):
    client, pack, mapping = seeded[PRIYA]
    report = seed(client, pack)
    assert (report.imported, report.present, report.ok) == (0, 30, True)
    assert report.mapping == mapping
    assert client.method("Email/query", calculateTotal=True, limit=1)["total"] == 30


def test_interrupted_import_reconciles(jmap):
    client = client_for(jmap, DANIEL)
    pack = build_pack(DANIEL)
    first = seed(client, pack, stop_after=11)
    assert first.interrupted and first.imported == 11 and not first.ok
    second = seed(client, pack)
    assert second.ok and (second.imported, second.present) == (19, 11)
    assert client.method("Email/query", calculateTotal=True, limit=1)["total"] == 30


def test_changed_content_under_known_message_id_is_reported_not_duplicated(seeded):
    client, pack, _ = seeded[NOAH]
    tampered = replace(pack[0], sha256="0" * 64)
    report = seed(client, [tampered])
    assert report.failed == [tampered.fixture_id] and report.imported == 0
    assert client.method("Email/query", calculateTotal=True, limit=1)["total"] == 30


def test_tag_round_trip_preserves_other_state(seeded):
    client, pack, mapping = seeded[PRIYA]
    target = next(f for f in pack if f.fixture_id == "mb-priya-c1-m1")
    email_id = mapping[target.fixture_id]
    before = get(client, email_id, "keywords", "mailboxIds", "preview")
    client.method("Email/set", update={email_id: {
        "keywords/needs-review": True, "keywords/follow-up": True}})
    client.method("Email/set", update={email_id: {"keywords/follow-up": None}})
    after = get(client, email_id, "keywords", "mailboxIds", "preview")
    assert set(after["keywords"]) == set(before["keywords"]) | {"needs-review"}
    assert "$seen" in after["keywords"]
    assert after["mailboxIds"] == before["mailboxIds"] and after["preview"] == before["preview"]


def test_tag_search_matches_manifest(seeded):
    for client, pack, mapping in seeded.values():
        for tag in ("needs-review", "follow-up", "waiting-on-customer"):
            ids = client.method("Email/query", filter={"hasKeyword": tag}, limit=50)["ids"]
            assert fixture_ids(client, ids, mapping) == {
                f.fixture_id for f in pack if tag in f.expected_tags}, tag


def test_text_search_semantics(seeded):
    client, pack, mapping = seeded[PRIYA]
    by_id = {f.fixture_id: f for f in pack}

    def found(**flt):
        return fixture_ids(client, client.method("Email/query", filter=flt, limit=50)["ids"],
                           mapping)

    assert found(text=by_id["mb-priya-s05"].token) == {"mb-priya-s05"}
    assert found(text=by_id["mb-priya-s05"].token.upper()) == {"mb-priya-s05"}  # case-insensitive
    assert found(subject="Quick question") == {"mb-priya-s10", "mb-priya-s11"}
    assert found(subject="quick", text="unrelated") == {"mb-priya-s11"}
    assert found(text="café") == {"mb-priya-s12"}
    sender = "alex.morgan@customer.example"
    from_alex = found(**{"from": sender})
    assert from_alex and from_alex == {
        f.fixture_id for f in pack
        if sender in message_from_bytes(f.raw, policy=policy.default)["From"].addresses[0].addr_spec}
    window = found(after="2026-10-01T09:00:00Z", before="2026-10-01T12:00:00Z")
    assert window == {f.fixture_id for f in pack[:3]}
    assert found(hasAttachment=True) == {"mb-priya-s13"}
    assert found(operator="AND", conditions=[
        {"hasKeyword": "needs-review"}, {"notKeyword": "$seen"}]) == {
        f.fixture_id for f in pack if "needs-review" in f.keywords and "$seen" not in f.keywords}
    not_support = found(operator="NOT", conditions=[{"hasKeyword": "support"}])
    assert not_support == {f.fixture_id for f in pack if "support" not in f.keywords}


def test_pagination_has_no_gaps_or_duplicates(seeded):
    client, pack, mapping = seeded[DANIEL]
    seen: list[str] = []
    while True:
        page = client.method("Email/query", position=len(seen), limit=7,
                             sort=[{"property": "receivedAt", "isAscending": True}],
                             calculateTotal=True)
        assert page["total"] == 30
        seen.extend(page["ids"])
        if len(page["ids"]) < 7:
            break
    assert len(seen) == len(set(seen)) == 30
    assert fixture_ids(client, seen, mapping) == {f.fixture_id for f in pack}
    assert [f for f in (fixture_ids(client, [i], mapping).pop() for i in seen)] == [
        f.fixture_id for f in pack]  # receivedAt ascending matches the controlled dates


def test_threads_follow_identifiers_not_subjects(seeded):
    client, _, mapping = seeded[PRIYA]
    ids = mapping
    thread = get(client, ids["mb-priya-c1-m2"], "threadId")["threadId"]
    members = client.method("Thread/get", ids=[thread])["list"][0]["emailIds"]
    assert fixture_ids(client, members, mapping) == {
        "mb-priya-c1-m1", "mb-priya-c1-m2", "mb-priya-c1-m3"}
    assert members == [ids["mb-priya-c1-m1"], ids["mb-priya-c1-m2"], ids["mb-priya-c1-m3"]]
    threads = {fid: get(client, ids[fid], "threadId")["threadId"]
               for fid in ("mb-priya-s10", "mb-priya-s11", "mb-priya-s15")}
    assert len(set(threads.values())) == 3  # same subject and a dangling reference stay apart
    assert len({get(client, ids[f"mb-priya-c{k}-m1"], "threadId")["threadId"]
                for k in range(1, 6)}) == 5


def test_out_of_order_import_still_joins_one_thread(jmap):
    client = client_for(jmap, PRIYA)
    chain = [f for f in build_pack(PRIYA) if f.thread_group == "mb-priya-c3"]
    seed(client, [chain[2], chain[0], chain[1]])
    threads = {item["threadId"] for item in client.method(
        "Email/get", ids=client.query_all(), properties=["threadId"])["list"]}
    assert len(threads) == 1


def test_thread_tagging_reports_partial_failure(seeded):
    client, _, mapping = seeded[PRIYA]
    members = [mapping[f"mb-priya-c2-m{n}"] for n in (1, 2, 3)]
    result = client.method("Email/set", update={
        **{i: {"keywords/follow-up": True} for i in members},
        "does-not-exist": {"keywords/follow-up": True}})
    assert set(result["updated"]) == set(members)
    assert result["notUpdated"]["does-not-exist"]["type"] == "notFound"
    other = mapping["mb-priya-c1-m1"]
    assert "follow-up" not in get(client, other, "keywords")["keywords"]


def test_read_unread_toggle_changes_only_seen(seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-c1-m3"]  # unread, tagged
    before = get(client, email_id, "keywords", "mailboxIds", "preview")
    assert "$seen" not in before["keywords"]
    client.method("Email/set", update={email_id: {"keywords/$seen": True}})
    seen = get(client, email_id, "keywords", "mailboxIds", "preview")
    assert set(seen["keywords"]) == set(before["keywords"]) | {"$seen"}
    client.method("Email/set", update={email_id: {"keywords/$seen": None}})
    assert get(client, email_id, "keywords", "mailboxIds", "preview") == before


def test_move_changes_membership_and_keeps_content(seeded):
    client, _, mapping = seeded[DANIEL]
    boxes = client.mailboxes()
    email_id = mapping["mb-daniel-s03"]
    before = get(client, email_id, "keywords", "preview", "mailboxIds")
    assert before["mailboxIds"] == {boxes["inbox"]: True}
    client.method("Email/set", update={email_id: {
        f"mailboxIds/{boxes['inbox']}": None, f"mailboxIds/{boxes['archive']}": True}})
    after = get(client, email_id, "keywords", "preview", "mailboxIds")
    assert after["mailboxIds"] == {boxes["archive"]: True}
    assert (after["keywords"], after["preview"]) == (before["keywords"], before["preview"])
    # A message must stay in at least one mailbox.
    result = client.method("Email/set", update={email_id: {"mailboxIds": {}}})
    assert result["notUpdated"][email_id]["type"] == "invalidProperties"


def test_draft_lifecycle_is_unsent_and_readable(seeded):
    client, _, mapping = seeded[PRIYA]
    boxes = client.mailboxes()
    blob = client.upload(ATTACHMENT_DATA, "text/csv")
    source = get(client, mapping["mb-priya-c1-m3"], "messageId", "references", "threadId")
    result = client.method("Email/set", create={"d": {
        "mailboxIds": {boxes["drafts"]: True}, "keywords": {"$draft": True, "$seen": True},
        "to": [{"name": "Alex Morgan", "email": "alex.morgan@customer.example"}],
        "subject": "Re: Export fails with E-5021",
        "inReplyTo": source["messageId"], "references": [*source["references"],
                                                          *source["messageId"]],
        "header:X-PersonaDesk-Artifact-Hash:asText": "abc123",
        "bodyValues": {"1": {"value": "Draft body with token zqdraftcheck."}},
        "textBody": [{"partId": "1", "type": "text/plain"}],
        "attachments": [{"blobId": blob, "name": "report.csv", "type": "text/csv"}]}})
    draft_id = result["created"]["d"]["id"]
    assert result["created"]["d"]["threadId"] == source["threadId"]  # joined the thread
    draft = client.method("Email/get", ids=[draft_id], fetchTextBodyValues=True, properties=[
        "to", "subject", "keywords", "mailboxIds", "bodyValues", "attachments",
        "header:X-PersonaDesk-Artifact-Hash:asText"])["list"][0]
    assert draft["to"] == [{"name": "Alex Morgan", "email": "alex.morgan@customer.example"}]
    assert "zqdraftcheck" in draft["bodyValues"]["1"]["value"]
    assert draft["keywords"] == {"$draft": True, "$seen": True}
    assert draft["mailboxIds"] == {boxes["drafts"]: True}
    assert draft["header:X-PersonaDesk-Artifact-Hash:asText"] == "abc123"
    att = draft["attachments"][0]
    assert hashlib.sha256(client.download(att["blobId"], att["name"])).hexdigest() == \
        hashlib.sha256(ATTACHMENT_DATA).hexdigest()
    found = client.method("Email/query", filter={"inMailbox": boxes["drafts"]})["ids"]
    assert found == [draft_id]


def test_only_drafts_can_be_created(seeded):
    client, _, _ = seeded[PRIYA]
    boxes = client.mailboxes()
    base = {"to": [{"email": "a@customer.example"}], "subject": "x",
            "bodyValues": {"1": {"value": "x"}}, "textBody": [{"partId": "1"}]}
    for name, obj in {
        "inbox": {**base, "mailboxIds": {boxes["inbox"]: True}, "keywords": {"$draft": True}},
        "no $draft": {**base, "mailboxIds": {boxes["drafts"]: True}, "keywords": {}},
        "spoofed header": {**base, "mailboxIds": {boxes["drafts"]: True},
                           "keywords": {"$draft": True}, "header:Bcc:asText": "x@y.example"},
        "no recipient": {**base, "to": [], "mailboxIds": {boxes["drafts"]: True},
                         "keywords": {"$draft": True}},
    }.items():
        result = client.method("Email/set", create={"d": obj})
        assert result["notCreated"]["d"]["type"] == "invalidProperties", name


def test_accounts_are_isolated_in_every_direction(seeded):
    personas = [PRIYA, DANIEL, NOAH]
    for owner in personas:
        _, _, owner_map = seeded[owner]
        owner_id = owner_map[f"mb-{PERSONAS[owner]['short']}-c1-m1"]
        for intruder in personas:
            if intruder == owner:
                continue
            client = seeded[intruder][0]
            result = client.method("Email/get", ids=[owner_id], properties=["subject"])
            assert result["list"] == [] and result["notFound"] == [owner_id]
            owner_client = seeded[owner][0]
            thread = get(owner_client, owner_id, "threadId", "blobId")
            assert client.method("Thread/get", ids=[thread["threadId"]])["notFound"]
            with pytest.raises(JmapError) as exc:
                client.download(thread["blobId"])
            assert exc.value.kind.endswith("notFound")
            with pytest.raises(JmapError) as exc:
                client.call(("Email/get", {"accountId": owner_client.account_id,
                                           "ids": [owner_id]}))
            assert exc.value.kind == "accountNotFound"
            patch = client.method("Email/set", update={owner_id: {"keywords/x": True}})
            assert patch["notUpdated"][owner_id]["type"] == "notFound"
            assert client.method("Email/set", destroy=[owner_id])["notDestroyed"]
    assert all(c.method("Email/query", calculateTotal=True, limit=1)["total"] == 30
               for c, _, _ in seeded.values())


def test_stale_state_is_detected_and_unrelated_keywords_survive(seeded):
    client, _, mapping = seeded[PRIYA]
    email_id = mapping["mb-priya-s04"]
    observed = client.method("Email/get", ids=[email_id], properties=["keywords"])["state"]
    other = JmapClient(client.base_url, PERSONAS[PRIYA]["address"], "personadesk-local")
    other.method("Email/set", update={email_id: {"keywords/waiting-on-customer": True}})
    with pytest.raises(JmapError) as exc:
        client.method("Email/set", ifInState=observed,
                      update={email_id: {"keywords/needs-review": True}})
    assert exc.value.kind == "stateMismatch"
    fresh = client.method("Email/get", ids=[email_id], properties=["keywords"])["state"]
    client.method("Email/set", ifInState=fresh, update={email_id: {"keywords/needs-review": True}})
    assert {"needs-review", "waiting-on-customer"} <= set(get(client, email_id, "keywords")["keywords"])


@pytest.mark.parametrize("conditional", [False, True])
def test_concurrent_updates_preserve_changes_and_check_state_atomically(
        jmap, seeded, monkeypatch, conditional):
    client, _, mapping = seeded[PRIYA]
    server = jmap[1]
    api = JmapApi(server.store, jmap[0])
    email_id = mapping["mb-priya-s04"]
    state = client.method("Email/get", ids=[email_id], properties=["keywords"])["state"]
    first_read, second_done = threading.Event(), threading.Event()
    original_get = server.store.get_email

    def paused_get(account_id, target):
        email = original_get(account_id, target)
        if threading.current_thread().name == "first-update":
            first_read.set()
            second_done.wait(timeout=1)
        return email

    monkeypatch.setattr(server.store, "get_email", paused_get)

    def update(tag, name):
        threading.current_thread().name = name
        args = {"accountId": client.account_id,
                "update": {email_id: {f"keywords/{tag}": True}}}
        if conditional:
            args["ifInState"] = state
        try:
            return api.handle(PERSONAS[PRIYA]["address"], {
                "methodCalls": [["Email/set", args, "u"]]})["methodResponses"][0]
        finally:
            if name == "second-update":
                second_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(update, "needs-review", "first-update")
        assert first_read.wait(timeout=5)
        second = pool.submit(update, "follow-up", "second-update")
        results = [first.result(timeout=10), second.result(timeout=10)]
    tags = get(client, email_id, "keywords")["keywords"]
    if conditional:
        assert sorted(r[0] for r in results) == ["Email/set", "error"]
        assert next(r[1]["type"] for r in results if r[0] == "error") == "stateMismatch"
        assert "needs-review" in tags and "follow-up" not in tags
    else:
        assert all(r[0] == "Email/set" for r in results)
        assert {"needs-review", "follow-up"} <= set(tags)


@pytest.mark.parametrize("command", ["jmap-reset", "jmap-serve"])
@pytest.mark.parametrize("explicit", [False, True])
def test_jmap_cli_selects_the_requested_database(root, tmp_path, monkeypatch, command, explicit):
    selected = tmp_path / "isolated.db" if explicit else cli.default_jmap_db(root)
    opened, reset, stopped = [], [], []

    class Store:
        def __init__(self, path):
            self.path = path
            opened.append(path)

        def reset(self):
            reset.append(self.path)

        def close(self):
            pass

    class Server(Store):
        base_url = "http://127.0.0.1:8088"

        def __init__(self, config, path, **kwargs):
            super().__init__(path)

        def start(self):
            return self

        def stop(self):
            stopped.append(self.path)

    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "JmapStore", Store)
    monkeypatch.setattr(cli, "JmapServer", Server)
    monkeypatch.setattr(cli.time, "sleep", interrupt)
    args = ["--root", str(root)]
    if explicit:
        args += ["--db", str(selected)]
    assert cli.main([*args, command]) == 0
    assert opened == [Path(selected)]
    assert reset == ([selected] if command == "jmap-reset" else [])
    assert stopped == ([selected] if command == "jmap-serve" else [])


def test_nothing_can_be_sent(jmap, seeded):
    client = seeded[PRIYA][0]
    session = client.session(refresh=True)
    assert "urn:ietf:params:jmap:submission" not in session["capabilities"]
    with pytest.raises(JmapError) as exc:
        client.method("EmailSubmission/set", create={"s": {}})
    assert exc.value.kind == "unknownMethod"
    response = client.http.post(session["apiUrl"], json={
        "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:submission"],
        "methodCalls": []})
    assert response.status_code == 400 and response.json()["type"].endswith("unknownCapability")
    with pytest.raises(ValueError):
        JmapServer(jmap[0], jmap[1].db_path.parent / "x.db", host="0.0.0.0", port=0)


def test_http_authentication_and_host_guard(jmap):
    config, server = jmap
    url = f"{server.base_url}/.well-known/jmap"
    assert requests.get(url, timeout=5).status_code == 401
    assert requests.get(url, auth=("priya.raman@company.example", "wrong"),
                        timeout=5).status_code == 401
    assert requests.get(url, auth=("nobody@company.example", config.password),
                        timeout=5).status_code == 401
    ok = requests.get(url, auth=("priya.raman@company.example", config.password), timeout=5)
    assert ok.status_code == 200 and len(ok.json()["accounts"]) == 1
    bad_host = requests.get(url, auth=("priya.raman@company.example", config.password),
                            headers={"Host": "evil.example"}, timeout=5)
    assert bad_host.status_code == 421


def test_failures_are_visible_not_empty(seeded):
    client = seeded[PRIYA][0]
    with pytest.raises(JmapError) as exc:
        client.method("Email/query", filter={"bogus": 1})
    assert exc.value.kind == "unsupportedFilter"
    with pytest.raises(JmapError):
        client.method("Email/get", ids=None)
    with pytest.raises(JmapError) as exc:
        client.method("Email/get", ids=[f"x{i}" for i in range(51)])
    assert exc.value.kind == "requestTooLarge"


def test_state_survives_restart_and_reset_is_scoped(jmap, root, tmp_path):
    config, server = jmap
    client = client_for(jmap, PRIYA)
    pack = build_pack(PRIYA)
    seed(client, pack)
    email_id = client.query_all()[0]
    client.method("Email/set", update={email_id: {"keywords/baseline": True}})
    db = server.db_path
    server.stop()
    again = JmapServer(config, db, port=0).start()
    try:
        client2 = JmapClient(again.base_url, PERSONAS[PRIYA]["address"], config.password)
        assert client2.method("Email/query", calculateTotal=True, limit=1)["total"] == 30
        assert "baseline" in get(client2, email_id, "keywords")["keywords"]
        again.store.reset()
        assert client2.method("Email/query", calculateTotal=True, limit=1)["total"] == 0
        assert seed(client2, pack).ok
        assert client2.method("Email/query", calculateTotal=True, limit=1)["total"] == 30
    finally:
        again.stop()
