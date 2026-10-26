"""Mail intake: turn unseen messages in the persona's local mailbox into reviewable jobs.

This is the PersonaDesk alternative to the Hermes email gateway's auto-reply: mail becomes a
persona-owned fixture under ``artifacts/inbox/<client_id>/`` and then an ordinary job, so
every draft still waits for human review. Standard library only (it runs inside Hermes).
"""

from __future__ import annotations

import email
import email.utils
import hashlib
import imaplib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from .paths import safe_child
from .permissions import PersonaGrant

MAILBOXES_RELATIVE = Path("config") / "mailboxes.json"
INBOX_RELATIVE = Path("artifacts") / "inbox"
FIXTURE_HEADER = "X-PersonaDesk-Fixture"
MAIL_PREFIX = "mail-"


@dataclass
class MailItem:
    uid: bytes
    message_id: str
    sender: str
    fixture: dict[str, Any] | None
    rejected: str | None = None


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_mailboxes(root: Path) -> dict[str, Any]:
    return json.loads((root / MAILBOXES_RELATIVE).read_text(encoding="utf-8"))


def persona_address(mailboxes: dict[str, Any], client_id: str) -> str:
    for address, spec in mailboxes["accounts"].items():
        if spec.get("persona") == client_id:
            return address
    raise KeyError(f"No mailbox is configured for persona {client_id}.")


def sender_authenticated(msg: EmailMessage, authserv_id: str, sender: str) -> bool:
    """Trust only the first Authentication-Results header, stamped by our own server."""
    results = msg.get_all("Authentication-Results") or []
    if not results:
        return False
    clauses = [c.strip().lower() for c in str(results[0]).split(";")]
    domain = sender.rpartition("@")[2]
    return clauses[0] == authserv_id.lower() and any(
        c.startswith("dmarc=pass") and f"header.from={domain}" in c for c in clauses[1:])


def mail_fixture(root: Path, grant: PersonaGrant, msg: EmailMessage,
                 mailboxes: dict[str, Any], now: datetime) -> dict[str, Any]:
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    message_id = str(msg.get("Message-ID", "")).strip()
    fixture_id = MAIL_PREFIX + hashlib.sha256(message_id.encode()).hexdigest()[:16]
    part = msg.get_body(preferencelist=("plain", "html"))
    body = part.get_content().strip() if part is not None else ""
    try:
        received = email.utils.parsedate_to_datetime(str(msg["Date"]))
    except (TypeError, ValueError):
        received = now
    if received.tzinfo is None:
        received = received.replace(tzinfo=UTC)
    facts = dict(mailboxes["accounts"].get(sender, {}).get("facts", {}))
    received_at, as_of = _iso(received), _iso(now)
    # A seeded fixture keeps its facts and clock only when it came from that fixture's sender.
    seeded = str(msg.get(FIXTURE_HEADER, "")).strip()
    if seeded:
        try:
            path = safe_child(root / "fixtures", grant.client_id, f"{seeded}.json")
            source = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except ValueError:
            source = None
        if source and source.get("from", "").lower() == sender:
            facts, received_at, as_of = source["facts"], source["received_at"], source["as_of"]
    return {
        "id": fixture_id, "client_id": grant.client_id, "version": 1, "split": "mail",
        "source_event_id": f"mail:{message_id}", "from": sender,
        "subject": str(msg.get("Subject", "")), "body": body,
        "received_at": received_at, "as_of": as_of, "facts": facts, "expected": {},
    }


def _connect(mailboxes: dict[str, Any], address: str, host: str | None,
             port: int | None) -> imaplib.IMAP4:
    server = mailboxes["server"]
    imap = imaplib.IMAP4(host or server["host"], port or server["imap_port"], timeout=15)
    imap.login(address, server["shared_password"])
    imap.select("INBOX")
    return imap


def fetch_unseen(root: Path, grant: PersonaGrant, *, limit: int = 10, host: str | None = None,
                 port: int | None = None) -> list[MailItem]:
    """Read (without marking seen) up to ``limit`` unseen messages from the persona's INBOX."""
    mailboxes = load_mailboxes(root)
    address = persona_address(mailboxes, grant.client_id)
    imap = _connect(mailboxes, address, host, port)
    items: list[MailItem] = []
    try:
        _, data = imap.uid("search", None, "UNSEEN")
        for uid in (data[0].split() if data and data[0] else [])[:limit]:
            status, fetched = imap.uid("fetch", uid, "(BODY.PEEK[])")
            raw = next((p[1] for p in fetched if isinstance(p, tuple)), None)
            if status != "OK" or raw is None:
                continue
            msg = email.message_from_bytes(raw, policy=policy.default)
            sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
            message_id = str(msg.get("Message-ID", "")).strip()
            if not message_id:
                items.append(MailItem(uid, "", sender, None, "missing Message-ID"))
            elif not sender_authenticated(msg, mailboxes["server"]["authserv_id"], sender):
                items.append(MailItem(uid, message_id, sender, None,
                                      "sender not authenticated by mailsim"))
            else:
                fixture = mail_fixture(root, grant, msg, mailboxes, datetime.now(UTC))
                items.append(MailItem(uid, message_id, sender, fixture))
    finally:
        imap.logout()
    return items


def write_fixture(root: Path, fixture: dict[str, Any]) -> Path:
    path = safe_child(root / INBOX_RELATIVE, fixture["client_id"], f"{fixture['id']}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def mark_seen(root: Path, grant: PersonaGrant, uids: list[bytes], *, host: str | None = None,
              port: int | None = None) -> None:
    if not uids:
        return
    mailboxes = load_mailboxes(root)
    imap = _connect(mailboxes, persona_address(mailboxes, grant.client_id), host, port)
    try:
        imap.uid("store", b",".join(uids).decode(), "+FLAGS.SILENT", r"(\Seen)")
    finally:
        imap.logout()
