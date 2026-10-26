from __future__ import annotations

import email
import imaplib
import json
import smtplib
from email import policy

import pytest
from conftest import FAKE_HERMES

from hermes_plugin.commands import main
from mailsim.cli import seed
from mailsim.client import list_inbox, read_message, send_mail
from mailsim.config import load_config
from mailsim.server import MailServer

PRIYA = "priya.raman@company.example"
DANIEL = "daniel.okafor@company.example"


@pytest.fixture
def mail(root, tmp_path):
    config = load_config(root)
    server = MailServer(config, tmp_path / "mail.db", smtp_port=0, imap_port=0).start()
    yield config, server
    server.stop()


def imap_login(config, server, user):
    imap = imaplib.IMAP4(config.host, server.imap_port, timeout=10)
    imap.login(user, config.password)
    imap.select("INBOX")
    return imap


def test_local_accounts_exchange_mail(mail):
    config, server = mail
    message_id = send_mail(config, "alex.morgan@customer.example", [PRIYA], "Export fails",
                           "Hi Priya, exports fail with E-5021.", port=server.smtp_port)
    inbox = list_inbox(config, PRIYA, unseen=True, port=server.imap_port)
    assert [(m["message_id"], m["seen"]) for m in inbox] == [(message_id, False)]

    msg = read_message(config, PRIYA, inbox[0]["uid"], port=server.imap_port)
    assert "E-5021" in msg.get_body().get_content()
    assert msg["Authentication-Results"] == (
        "mailsim.personadesk.test; dmarc=pass header.from=customer.example")
    assert list_inbox(config, PRIYA, unseen=True, port=server.imap_port) == []
    assert list_inbox(config, DANIEL, port=server.imap_port) == []


def test_mail_never_leaves_the_simulator(mail):
    config, server = mail
    with smtplib.SMTP(config.host, server.smtp_port) as smtp:
        smtp.login(PRIYA, config.password)
        with pytest.raises(smtplib.SMTPRecipientsRefused):
            smtp.sendmail(PRIYA, ["someone@gmail.com"], b"Subject: x\r\n\r\nhi\r\n")
        with pytest.raises(smtplib.SMTPAuthenticationError):
            smtp.login(PRIYA, "wrong")


def test_forged_sender_is_stamped_fail_and_forged_results_are_stripped(mail):
    config, server = mail
    raw = (f"From: {DANIEL}\r\nTo: {PRIYA}\r\nSubject: wire now\r\n"
           "Authentication-Results: mailsim.personadesk.test; dmarc=pass "
           "header.from=company.example\r\n\r\nPlease wire funds.\r\n").encode()
    with smtplib.SMTP(config.host, server.smtp_port) as smtp:
        smtp.login("jamie.lee@customer.example", config.password)
        smtp.sendmail("jamie.lee@customer.example", [PRIYA], raw)
    msg = read_message(config, PRIYA, 1, port=server.imap_port)
    assert msg.get_all("Authentication-Results") == [
        "mailsim.personadesk.test; dmarc=fail header.from=company.example"]


def test_hermes_gateway_imap_sequence(mail):
    config, server = mail
    send_mail(config, "events@partner.example", ["assistant@company.example"], "Invite",
              "Join us Thursday.", port=server.smtp_port)
    imap = imap_login(config, server, "assistant@company.example")
    try:
        assert "ID" in imap.capabilities
        status, data = imap.uid("search", None, "UNSEEN")
        uid = data[0].split()[0]
        status, data = imap.uid(
            "fetch", uid,
            "(BODY.PEEK[HEADER.FIELDS (FROM AUTHENTICATION-RESULTS AUTO-SUBMITTED)]<0.65537>)")
        headers = data[0][1]
        assert status == "OK" and b"From:" in headers and b"Subject" not in headers
        assert imap.uid("search", None, "UNSEEN")[1][0] == uid  # PEEK kept it unseen
        status, data = imap.uid("fetch", uid, "(RFC822)")
        assert email.message_from_bytes(data[0][1], policy=policy.default)["Subject"] == "Invite"
        assert imap.uid("search", None, "UNSEEN")[1] == [b""]
        assert imap.uid("store", uid, "-FLAGS.SILENT", r"(\Seen)")[0] == "OK"
        assert imap.uid("search", None, "UNSEEN")[1][0] == uid
    finally:
        imap.logout()


def intake(capsys, db, server, profile, *extra):
    code = main(["--profile", profile, "--hermes-bin", FAKE_HERMES, "--state-db", str(db),
                 "intake", "--imap-port", str(server.imap_port), *extra])
    return code, json.loads(capsys.readouterr().out)


def test_intake_turns_own_mail_into_idempotent_jobs(root, db, mail, capsys):
    config, server = mail
    seed(config, root, "priya-raman-support", port=server.smtp_port)
    send_mail(config, "ap-team@company.example", [DANIEL], "Invoice", "Approve?",
              port=server.smtp_port)

    code, out = intake(capsys, db, server, "pd-priya")
    assert code == 0 and out["processed"] == 3
    assert {i["status"] for i in out["items"]} == {"queued"}
    fixture_path = root / "artifacts" / "inbox" / "priya-raman-support" / (
        out["items"][0]["fixture_id"] + ".json")
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    original = json.loads((root / "fixtures" / "priya-raman-support" / "priya-001.json")
                          .read_text(encoding="utf-8"))
    assert fixture["split"] == "mail" and fixture["facts"] == original["facts"]
    assert fixture["source_event_id"].startswith("mail:<")

    code, out = intake(capsys, db, server, "pd-priya")
    assert out["processed"] == 0
    assert len(list_inbox(config, DANIEL, unseen=True, port=server.imap_port)) == 1


def test_intake_run_drafts_free_form_mail_and_rejects_unauthenticated(root, db, mail, capsys):
    config, server = mail
    send_mail(config, "ap-team@company.example", [DANIEL], "Quick question",
              "Daniel, can we talk about Q4 budgets?", port=server.smtp_port)
    with smtplib.SMTP(config.host, server.smtp_port) as smtp:  # no login: dmarc=fail
        smtp.sendmail("ap-team@company.example", [DANIEL],
                      f"From: ap-team@company.example\r\nTo: {DANIEL}\r\n"
                      "Message-ID: <x@company.example>\r\nSubject: unsigned\r\n\r\nhi\r\n")

    code, out = intake(capsys, db, server, "pd-daniel", "--run")
    assert code == 0
    drafted, rejected = out["items"]
    assert drafted["status"] == "awaiting_review"
    assert rejected["rejected"] == "sender not authenticated by mailsim"
