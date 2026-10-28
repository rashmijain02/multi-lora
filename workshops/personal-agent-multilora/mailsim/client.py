"""Plain ``smtplib``/``imaplib`` helpers: what any mail client would do against mailsim."""

from __future__ import annotations

import email
import email.utils
import imaplib
import smtplib
from email import policy
from email.message import EmailMessage
from typing import Any

from .config import MailConfig


def send_mail(config: MailConfig, sender: str, to: list[str], subject: str, body: str, *,
              in_reply_to: str | None = None, headers: dict[str, str] | None = None,
              port: int | None = None) -> str:
    account = config.account(sender)
    if account is None:
        raise ValueError(f"{sender} is not a mailsim account; see `pd-mail accounts`.")
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((account.name, account.address))
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg["Message-ID"] = email.utils.make_msgid(domain=account.address.rpartition("@")[2])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    for name, value in (headers or {}).items():
        msg[name] = value
    msg.set_content(body)
    with smtplib.SMTP(config.host, port or config.smtp_port, timeout=15) as smtp:
        smtp.login(account.address, config.password)
        smtp.send_message(msg)
    return msg["Message-ID"]


def _imap(config: MailConfig, user: str, port: int | None) -> imaplib.IMAP4:
    imap = imaplib.IMAP4(config.host, port or config.imap_port, timeout=15)
    imap.login(user, config.password)
    imap.select("INBOX")
    return imap


def _payload(data: list[Any]) -> bytes:
    for part in data:
        if isinstance(part, tuple) and len(part) == 2:
            return part[1]
    raise ValueError("Message not found.")


def list_inbox(config: MailConfig, user: str, *, unseen: bool = False,
               port: int | None = None) -> list[dict[str, Any]]:
    imap = _imap(config, user, port)
    try:
        _, data = imap.uid("search", None, "UNSEEN" if unseen else "ALL")
        rows = []
        for uid in (data[0].split() if data and data[0] else []):
            _, fetched = imap.uid(
                "fetch", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            head = email.message_from_bytes(_payload(fetched), policy=policy.default)
            flags = b" ".join(p[0] if isinstance(p, tuple) else p for p in fetched)
            rows.append({"uid": int(uid), "from": str(head["From"]),
                         "subject": str(head["Subject"]), "date": str(head["Date"]),
                         "message_id": str(head["Message-ID"]), "seen": b"\\Seen" in flags})
        return rows
    finally:
        imap.logout()


def read_message(config: MailConfig, user: str, uid: int, *, mark_seen: bool = True,
                 port: int | None = None) -> EmailMessage:
    imap = _imap(config, user, port)
    try:
        item = "(RFC822)" if mark_seen else "(BODY.PEEK[])"
        status, data = imap.uid("fetch", str(uid), item)
        if status != "OK":
            raise ValueError(f"Cannot fetch UID {uid}.")
        return email.message_from_bytes(_payload(data), policy=policy.default)
    finally:
        imap.logout()


def body_text(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    return part.get_content().strip() if part is not None else ""
