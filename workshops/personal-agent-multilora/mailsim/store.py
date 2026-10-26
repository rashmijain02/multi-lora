"""SQLite mailbox store: one INBOX per local account, IMAP-style UIDs and flags."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS mailboxes (
    owner TEXT PRIMARY KEY,
    uidvalidity INTEGER NOT NULL,
    uidnext INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    owner TEXT NOT NULL,
    uid INTEGER NOT NULL,
    flags TEXT NOT NULL DEFAULT '',
    internal_date REAL NOT NULL,
    raw BLOB NOT NULL,
    PRIMARY KEY (owner, uid)
);
"""


class MailStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def _mailbox(self, owner: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM mailboxes WHERE owner = ?", (owner,)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO mailboxes VALUES (?, ?, 1)", (owner, int(time.time())))
            row = self.conn.execute("SELECT * FROM mailboxes WHERE owner = ?", (owner,)).fetchone()
        return row

    def status(self, owner: str) -> dict[str, int]:
        with self.conn:
            box = self._mailbox(owner)
        return {"uidvalidity": box["uidvalidity"], "uidnext": box["uidnext"]}

    def deliver(self, owner: str, raw: bytes) -> int:
        with self.conn:
            uid = self._mailbox(owner)["uidnext"]
            self.conn.execute("UPDATE mailboxes SET uidnext = ? WHERE owner = ?", (uid + 1, owner))
            self.conn.execute(
                "INSERT INTO messages (owner, uid, flags, internal_date, raw) VALUES (?,?,?,?,?)",
                (owner, uid, "", time.time(), raw))
        return uid

    def messages(self, owner: str) -> list[dict[str, Any]]:
        """Messages in sequence order (sequence number = list index + 1)."""
        rows = self.conn.execute(
            "SELECT uid, flags, internal_date, raw FROM messages WHERE owner = ? ORDER BY uid",
            (owner,)).fetchall()
        return [{"uid": r["uid"], "flags": set(r["flags"].split()), "internal_date":
                 r["internal_date"], "raw": bytes(r["raw"])} for r in rows]

    def set_flags(self, owner: str, uid: int, flags: set[str]) -> None:
        with self.conn:
            self.conn.execute("UPDATE messages SET flags = ? WHERE owner = ? AND uid = ?",
                              (" ".join(sorted(flags)), owner, uid))

    def expunge(self, owner: str) -> list[int]:
        """Delete ``\\Deleted`` messages; return their former sequence numbers (descending)."""
        removed = [i + 1 for i, m in enumerate(self.messages(owner)) if "\\Deleted" in m["flags"]]
        with self.conn:
            self.conn.execute(
                "DELETE FROM messages WHERE owner = ? AND (' ' || flags || ' ') LIKE '% \\Deleted %'",
                (owner,))
        return sorted(removed, reverse=True)

    def reset(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM messages")
            self.conn.execute("DELETE FROM mailboxes")
