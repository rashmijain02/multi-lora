"""Application records: jobs, canonical drafts, and reviews.

Inside Hermes this uses ``plugin_db("personadesk")`` (profile-scoped SQLite under
``<HERMES_HOME>/plugin-data/personadesk/``). Tests and the standalone CLI pass an explicit
database path. Native Hermes session IDs are referenced, never copied.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evidence import content_hash

STATE_DB_ENV = "PERSONADESK_STATE_DB"
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    principal TEXT NOT NULL,
    client_id TEXT NOT NULL,
    profile TEXT NOT NULL,
    fixture_id TEXT NOT NULL,
    task TEXT NOT NULL,
    release_id TEXT,
    status TEXT NOT NULL,
    hermes_session_id TEXT,
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    revision INTEGER NOT NULL,
    client_id TEXT NOT NULL,
    body TEXT NOT NULL,
    evidence TEXT NOT NULL,
    uncertainties TEXT NOT NULL,
    blocked_actions TEXT NOT NULL,
    writer TEXT NOT NULL,
    artifact_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (job_id, revision)
);
CREATE TABLE IF NOT EXISTS reviews (
    review_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    draft_hash TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    decision TEXT NOT NULL,
    edited_text TEXT,
    reason TEXT,
    learning_consent INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""

TRANSITIONS = {
    "queued": {"running", "cancelled"},
    "running": {"awaiting_review", "failed", "cancelled"},
    "awaiting_review": {"approved", "rejected"},
    "failed": {"queued"},
    "approved": set(),
    "rejected": set(),
    "cancelled": set(),
}


class InvalidTransition(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def draft_hash(job_id: str, revision: int, client_id: str, body: str, evidence: list) -> str:
    canonical = json.dumps(
        {"job_id": job_id, "revision": revision, "client_id": client_id, "body": body,
         "evidence": evidence},
        sort_keys=True, separators=(",", ":"),
    )
    return content_hash(canonical)


@dataclass
class Store:
    conn: sqlite3.Connection

    def __post_init__(self) -> None:
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    @property
    def path(self) -> str | None:
        """The database file, or ``None`` for an in-memory store."""
        row = self.conn.execute("PRAGMA database_list").fetchone()
        return row[2] or None

    # ---- jobs -------------------------------------------------------------------------
    def create_job(
        self, *, source_key: str, principal: str, client_id: str, profile: str,
        fixture_id: str, task: str, release_id: str | None,
    ) -> tuple[dict[str, Any], bool]:
        """Return ``(job, created)``. A repeated source key returns the existing job."""
        existing = self.conn.execute(
            "SELECT * FROM jobs WHERE source_key = ?", (source_key,)
        ).fetchone()
        if existing:
            job = dict(existing)
            if (job["client_id"], job["fixture_id"], job["task"]) != (client_id, fixture_id, task):
                raise ValueError("source_key already used for a different request.")
            return job, False
        now = _now()
        job_id = "job-" + uuid.uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO jobs (job_id, source_key, principal, client_id, profile, fixture_id,"
            " task, release_id, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
            (job_id, source_key, principal, client_id, profile, fixture_id, task, release_id,
             now, now),
        )
        self.conn.commit()
        return self.get_job(job_id), True

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown job {job_id}")
        return dict(row)

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, job_id LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def transition(self, job_id: str, new: str, **fields: Any) -> dict[str, Any]:
        job = self.get_job(job_id)
        if new not in TRANSITIONS[job["status"]]:
            raise InvalidTransition(f"{job_id}: {job['status']} -> {new} is not allowed.")
        allowed = {"hermes_session_id", "error"}
        if set(fields) - allowed:
            raise ValueError(f"Unexpected fields {set(fields) - allowed}")
        sets = ["status = ?", "updated_at = ?"]
        values: list[Any] = [new, _now()]
        if new == "running":
            sets.append("attempts = attempts + 1")
            sets.append("error = NULL")  # each attempt reports only its own failure
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            values.append(value)
        cursor = self.conn.execute(
            f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ? AND status = ?",
            (*values, job_id, job["status"]),
        )
        if cursor.rowcount != 1:
            self.conn.rollback()
            raise InvalidTransition(f"{job_id} changed concurrently.")
        self.conn.commit()
        return self.get_job(job_id)

    # ---- drafts -----------------------------------------------------------------------
    def save_draft(
        self, *, job_id: str, client_id: str, body: str, evidence: list[dict[str, Any]],
        uncertainties: list[str], blocked_actions: list[str], writer: dict[str, Any],
    ) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job["client_id"] != client_id:
            raise PermissionError("Draft persona does not match its job.")
        if job["status"] != "running":
            raise InvalidTransition(f"Drafts can be saved only while {job_id} is running.")
        row = self.conn.execute(
            "SELECT COALESCE(MAX(revision), 0) FROM drafts WHERE job_id = ?", (job_id,)
        ).fetchone()
        revision = int(row[0]) + 1
        artifact = draft_hash(job_id, revision, client_id, body, evidence)
        draft_id = f"{job_id}-r{revision}"
        self.conn.execute(
            "INSERT INTO drafts (draft_id, job_id, revision, client_id, body, evidence,"
            " uncertainties, blocked_actions, writer, artifact_hash, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (draft_id, job_id, revision, client_id, body, json.dumps(evidence),
             json.dumps(uncertainties), json.dumps(blocked_actions), json.dumps(writer),
             artifact, _now()),
        )
        self.conn.commit()
        return self.latest_draft(job_id)

    def latest_draft(self, job_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM drafts WHERE job_id = ? ORDER BY revision DESC LIMIT 1", (job_id,)
        ).fetchone()
        if row is None:
            return None
        draft = dict(row)
        for key in ("evidence", "uncertainties", "blocked_actions", "writer"):
            draft[key] = json.loads(draft[key])
        return draft

    # ---- reviews ----------------------------------------------------------------------
    def record_review(
        self, *, job_id: str, reviewer: str, presented_hash: str, decision: str,
        edited_text: str | None, reason: str | None, learning_consent: bool,
    ) -> dict[str, Any]:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject.")
        draft = self.latest_draft(job_id)
        if draft is None:
            raise InvalidTransition(f"{job_id} has no draft to review.")
        if presented_hash != draft["artifact_hash"]:
            raise InvalidTransition(
                "Draft hash mismatch: the reviewed artifact is not the latest revision."
            )
        review_id = "rev-" + uuid.uuid4().hex[:12]
        # The review row and the state change commit together or not at all.
        self.conn.execute(
            "INSERT INTO reviews (review_id, job_id, draft_hash, reviewer, decision,"
            " edited_text, reason, learning_consent, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (review_id, job_id, presented_hash, reviewer, decision, edited_text, reason,
             int(learning_consent), _now()),
        )
        try:
            self.transition(job_id, "approved" if decision == "approve" else "rejected")
        except Exception:
            self.conn.rollback()
            raise
        return dict(
            self.conn.execute("SELECT * FROM reviews WHERE review_id = ?", (review_id,)).fetchone()
        )

    def reviews(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM reviews ORDER BY created_at")]


def open_store(db_path: Path | None = None) -> Store:
    """Open the job store: explicit path, ``PERSONADESK_STATE_DB``, else Hermes plugin_db."""
    if db_path is None and os.environ.get(STATE_DB_ENV):
        db_path = Path(os.environ[STATE_DB_ENV]).expanduser()
    if db_path is not None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        return Store(conn)
    from plugins.plugin_storage import plugin_db  # type: ignore[import-not-found]

    return Store(plugin_db("personadesk"))
