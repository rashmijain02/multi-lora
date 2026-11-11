"""SQLite store behind the JMAP playground: mailboxes, threads, keywords, and blobs.

Separate from the IMAP store (``store.py``): that one models a single INBOX with IMAP flags,
this one models what the JMAP Mail objects need (several mailboxes per account, keyword sets,
RFC 8621-style threads, and content-addressed blobs). Everything is scoped by ``account_id``,
and every read or write takes the account explicitly, so one account can never reach another's
rows by guessing an ID.

Scale is deliberately small (hundreds of messages), so filtering and sorting happen in Python
over decoded rows instead of in SQL.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY,
    address TEXT UNIQUE NOT NULL,
    state INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mailboxes (
    account_id TEXT NOT NULL,
    mailbox_id TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT,
    PRIMARY KEY (account_id, mailbox_id)
);
CREATE TABLE IF NOT EXISTS emails (
    account_id TEXT NOT NULL,
    email_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    blob_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    in_reply_to TEXT NOT NULL,
    refs TEXT NOT NULL,
    subject TEXT NOT NULL,
    sender TEXT NOT NULL,
    recipients TEXT NOT NULL,
    cc TEXT NOT NULL,
    sent_at TEXT,
    received_at REAL NOT NULL,
    size INTEGER NOT NULL,
    body_text TEXT NOT NULL,
    keywords TEXT NOT NULL,
    attachments TEXT NOT NULL,
    headers TEXT NOT NULL,
    PRIMARY KEY (account_id, email_id)
);
CREATE TABLE IF NOT EXISTS email_mailboxes (
    account_id TEXT NOT NULL,
    email_id TEXT NOT NULL,
    mailbox_id TEXT NOT NULL,
    PRIMARY KEY (account_id, email_id, mailbox_id)
);
CREATE TABLE IF NOT EXISTS links (
    account_id TEXT NOT NULL,
    email_id TEXT NOT NULL,
    token TEXT NOT NULL,
    own INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS links_token ON links (account_id, token);
CREATE TABLE IF NOT EXISTS blobs (
    account_id TEXT NOT NULL,
    blob_id TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (account_id, blob_id)
);
"""

DEFAULT_MAILBOXES = (("Inbox", "inbox"), ("Drafts", "drafts"), ("Sent", "sent"),
                     ("Archive", "archive"), ("Trash", "trash"))
_TOKEN = re.compile(r"\w+")
_ANGLE = re.compile(r"<([^<>\s]+)>")


class StoreError(Exception):
    """A request the store refuses (the protocol layer turns it into a JMAP error)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def tokens(text: str) -> set[str]:
    """Search tokens: case-folded runs of word characters (CJK without spaces is one token)."""
    return set(_TOKEN.findall(text.casefold()))


def account_id_for(address: str) -> str:
    return "u" + hashlib.sha256(address.strip().lower().encode()).hexdigest()[:12]


def _new_id(prefix: str) -> str:
    return prefix + secrets.token_hex(8)


def parse_message(raw: bytes) -> dict[str, Any]:
    """Extract the fields JMAP needs from an RFC 5322 message."""
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    def addresses(header: str) -> list[dict[str, str]]:
        return [{"name": name, "email": addr.lower()}
                for name, addr in getaddresses([str(v) for v in msg.get_all(header, [])]) if addr]

    ids = _ANGLE.findall(str(msg["message-id"] or ""))
    message_id = ids[0] if ids else f"{secrets.token_hex(12)}@generated.personadesk.test"
    in_reply_to = _ANGLE.findall(str(msg["in-reply-to"] or ""))
    refs = _ANGLE.findall(str(msg["references"] or ""))
    sent_at = None
    if msg["date"]:
        try:
            sent_at = parsedate_to_datetime(str(msg["date"])).isoformat()
        except (TypeError, ValueError):
            sent_at = None
    body = msg.get_body(preferencelist=("plain",))
    if body is not None:
        text = body.get_content()
    else:
        html = msg.get_body(preferencelist=("html",))
        text = re.sub(r"<[^>]+>", " ", html.get_content()) if html is not None else ""
    attachments = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True) or b""
        attachments.append({"name": part.get_filename() or "attachment",
                            "type": part.get_content_type(), "data": data})
    custom = {name.lower(): str(value) for name, value in msg.items()
              if name.lower().startswith("x-")}
    return {
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "refs": refs,
        "subject": str(msg["subject"] or ""),
        "sender": addresses("from"),
        "recipients": addresses("to"),
        "cc": addresses("cc"),
        "sent_at": sent_at,
        "body_text": text,
        "attachments": attachments,
        "headers": custom,
    }


class JmapStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- accounts, state, mailboxes ----------------------------------------------------
    def ensure_account(self, address: str) -> str:
        address = address.strip().lower()
        account_id = account_id_for(address)
        with self.lock, self.conn:
            if self.conn.execute("SELECT 1 FROM accounts WHERE account_id = ?",
                                 (account_id,)).fetchone() is None:
                self.conn.execute("INSERT INTO accounts (account_id, address) VALUES (?, ?)",
                                  (account_id, address))
                for name, role in DEFAULT_MAILBOXES:
                    mailbox_id = "m" + hashlib.sha1(f"{account_id}:{role}".encode()).hexdigest()[:10]
                    self.conn.execute(
                        "INSERT INTO mailboxes (account_id, mailbox_id, name, role)"
                        " VALUES (?, ?, ?, ?)", (account_id, mailbox_id, name, role))
        return account_id

    def state(self, account_id: str) -> str:
        with self.lock:
            row = self.conn.execute("SELECT state FROM accounts WHERE account_id = ?",
                                    (account_id,)).fetchone()
        return f"s{row['state'] if row else 0}"

    def _bump(self, account_id: str) -> None:
        self.conn.execute("UPDATE accounts SET state = state + 1 WHERE account_id = ?",
                          (account_id,))

    def mailboxes(self, account_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT mailbox_id, name, role FROM mailboxes WHERE account_id = ?"
                " ORDER BY name", (account_id,)).fetchall()
            counts = {r["mailbox_id"]: (r["total"], r["unread"]) for r in self.conn.execute(
                "SELECT em.mailbox_id AS mailbox_id, COUNT(*) AS total,"
                " SUM(CASE WHEN e.keywords LIKE '%\"$seen\"%' THEN 0 ELSE 1 END) AS unread"
                " FROM email_mailboxes em JOIN emails e ON e.account_id = em.account_id"
                " AND e.email_id = em.email_id WHERE em.account_id = ? GROUP BY em.mailbox_id",
                (account_id,))}
        return [{"id": r["mailbox_id"], "name": r["name"], "role": r["role"],
                 "totalEmails": counts.get(r["mailbox_id"], (0, 0))[0],
                 "unreadEmails": counts.get(r["mailbox_id"], (0, 0))[1] or 0} for r in rows]

    def mailbox_by_role(self, account_id: str, role: str) -> str:
        for box in self.mailboxes(account_id):
            if box["role"] == role:
                return box["id"]
        raise StoreError("notFound", f"No mailbox with role {role!r}.")

    # ---- blobs -----------------------------------------------------------------------
    def put_blob(self, account_id: str, data: bytes, content_type: str) -> str:
        blob_id = "G" + hashlib.sha256(data).hexdigest()[:24]
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs (account_id, blob_id, content_type, data)"
                " VALUES (?, ?, ?, ?)", (account_id, blob_id, content_type, data))
        return blob_id

    def get_blob(self, account_id: str, blob_id: str) -> tuple[bytes, str] | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT data, content_type FROM blobs WHERE account_id = ? AND blob_id = ?",
                (account_id, blob_id)).fetchone()
        return (bytes(row["data"]), row["content_type"]) if row else None

    # ---- emails ----------------------------------------------------------------------
    def _decode(self, row: sqlite3.Row, mailbox_ids: list[str]) -> dict[str, Any]:
        return {
            "id": row["email_id"], "threadId": row["thread_id"], "blobId": row["blob_id"],
            "messageId": row["message_id"], "inReplyTo": json.loads(row["in_reply_to"]),
            "references": json.loads(row["refs"]), "subject": row["subject"],
            "from": json.loads(row["sender"]), "to": json.loads(row["recipients"]),
            "cc": json.loads(row["cc"]), "sentAt": row["sent_at"],
            "receivedAt": row["received_at"], "size": row["size"], "body": row["body_text"],
            "keywords": json.loads(row["keywords"]), "attachments": json.loads(row["attachments"]),
            "headers": json.loads(row["headers"]), "mailboxIds": sorted(mailbox_ids),
        }

    def all_emails(self, account_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM emails WHERE account_id = ?",
                                     (account_id,)).fetchall()
            membership: dict[str, list[str]] = {}
            for r in self.conn.execute(
                    "SELECT email_id, mailbox_id FROM email_mailboxes WHERE account_id = ?",
                    (account_id,)):
                membership.setdefault(r["email_id"], []).append(r["mailbox_id"])
        return [self._decode(r, membership.get(r["email_id"], [])) for r in rows]

    def get_email(self, account_id: str, email_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM emails WHERE account_id = ? AND email_id = ?",
                                    (account_id, email_id)).fetchone()
            if row is None:
                return None
            boxes = [r["mailbox_id"] for r in self.conn.execute(
                "SELECT mailbox_id FROM email_mailboxes WHERE account_id = ? AND email_id = ?",
                (account_id, email_id))]
        return self._decode(row, boxes)

    def thread_email_ids(self, account_id: str, thread_id: str) -> list[str] | None:
        with self.lock:
            rows = self.conn.execute(
                "SELECT email_id FROM emails WHERE account_id = ? AND thread_id = ?"
                " ORDER BY received_at, email_id", (account_id, thread_id)).fetchall()
        return [r["email_id"] for r in rows] or None

    def import_message(self, account_id: str, raw: bytes, mailbox_ids: list[str],
                       keywords: list[str], received_at: float | None = None) -> dict[str, Any]:
        """Store one message, assign its thread from Message-ID/In-Reply-To/References only.

        Two messages share a thread only when their identifiers link them. A shared subject
        never does, so unrelated same-subject mail stays separate.
        """
        parsed = parse_message(raw)
        with self.lock, self.conn:
            known = {r["mailbox_id"] for r in self.conn.execute(
                "SELECT mailbox_id FROM mailboxes WHERE account_id = ?", (account_id,))}
            if not mailbox_ids or not set(mailbox_ids) <= known:
                raise StoreError("invalidProperties", "mailboxIds must name existing mailboxes.")
            email_id = _new_id("M")
            ancestors = set(parsed["in_reply_to"]) | set(parsed["refs"])
            linked: set[str] = set()
            marks = ",".join("?" for _ in ancestors)
            if ancestors:
                linked |= {r["email_id"] for r in self.conn.execute(
                    f"SELECT email_id FROM links WHERE account_id = ? AND own = 1"
                    f" AND token IN ({marks})", (account_id, *ancestors))}
            linked |= {r["email_id"] for r in self.conn.execute(
                "SELECT email_id FROM links WHERE account_id = ? AND own = 0 AND token = ?",
                (account_id, parsed["message_id"]))}
            thread_ids = sorted({r["thread_id"] for r in self.conn.execute(
                f"SELECT thread_id FROM emails WHERE account_id = ? AND email_id IN"
                f" ({','.join('?' for _ in linked) or 'NULL'})", (account_id, *linked))})
            thread_id = thread_ids[0] if thread_ids else _new_id("T")
            for other in thread_ids[1:]:  # a late message can join two earlier threads
                self.conn.execute("UPDATE emails SET thread_id = ? WHERE account_id = ?"
                                  " AND thread_id = ?", (thread_id, account_id, other))
            blob_id = self.put_blob(account_id, raw, "message/rfc822")
            stored_attachments = []
            for part in parsed["attachments"]:
                part_blob = self.put_blob(account_id, part["data"], part["type"])
                stored_attachments.append({
                    "blobId": part_blob, "name": part["name"], "type": part["type"],
                    "size": len(part["data"]), "sha256": hashlib.sha256(part["data"]).hexdigest()})
            self.conn.execute(
                "INSERT INTO emails VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, email_id, thread_id, blob_id, parsed["message_id"],
                 json.dumps(parsed["in_reply_to"]), json.dumps(parsed["refs"]),
                 parsed["subject"], json.dumps(parsed["sender"]), json.dumps(parsed["recipients"]),
                 json.dumps(parsed["cc"]), parsed["sent_at"], received_at or time.time(),
                 len(raw), parsed["body_text"], json.dumps(sorted({k.lower() for k in keywords})),
                 json.dumps(stored_attachments), json.dumps(parsed["headers"])))
            for mailbox_id in mailbox_ids:
                self.conn.execute("INSERT INTO email_mailboxes VALUES (?,?,?)",
                                  (account_id, email_id, mailbox_id))
            self.conn.execute("INSERT INTO links VALUES (?,?,?,1)",
                              (account_id, email_id, parsed["message_id"]))
            for ref in sorted(ancestors):
                self.conn.execute("INSERT INTO links VALUES (?,?,?,0)", (account_id, email_id, ref))
            self._bump(account_id)
        return {"id": email_id, "blobId": blob_id, "threadId": thread_id, "size": len(raw)}

    def update_email(self, account_id: str, email_id: str, keywords: list[str] | None = None,
                     mailbox_ids: list[str] | None = None) -> None:
        with self.lock, self.conn:
            if self.conn.execute("SELECT 1 FROM emails WHERE account_id = ? AND email_id = ?",
                                 (account_id, email_id)).fetchone() is None:
                raise StoreError("notFound", "No such email.")
            if keywords is not None:
                self.conn.execute("UPDATE emails SET keywords = ? WHERE account_id = ?"
                                  " AND email_id = ?", (json.dumps(sorted(set(keywords))),
                                                        account_id, email_id))
            if mailbox_ids is not None:
                known = {r["mailbox_id"] for r in self.conn.execute(
                    "SELECT mailbox_id FROM mailboxes WHERE account_id = ?", (account_id,))}
                if not mailbox_ids or not set(mailbox_ids) <= known:
                    raise StoreError("invalidProperties",
                                     "mailboxIds must be a non-empty set of existing mailboxes.")
                self.conn.execute("DELETE FROM email_mailboxes WHERE account_id = ?"
                                  " AND email_id = ?", (account_id, email_id))
                for mailbox_id in mailbox_ids:
                    self.conn.execute("INSERT INTO email_mailboxes VALUES (?,?,?)",
                                      (account_id, email_id, mailbox_id))
            self._bump(account_id)

    def destroy_email(self, account_id: str, email_id: str) -> None:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM emails WHERE account_id = ? AND email_id = ?",
                                    (account_id, email_id))
            if cur.rowcount == 0:
                raise StoreError("notFound", "No such email.")
            for table in ("email_mailboxes", "links"):
                self.conn.execute(f"DELETE FROM {table} WHERE account_id = ? AND email_id = ?",
                                  (account_id, email_id))
            self._bump(account_id)

    def reset(self) -> None:
        """Delete only this playground's data."""
        with self.lock, self.conn:
            for table in ("links", "email_mailboxes", "emails", "blobs", "mailboxes", "accounts"):
                self.conn.execute(f"DELETE FROM {table}")
