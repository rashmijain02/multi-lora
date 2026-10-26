"""Operator commands: ``hermes personadesk run|status|show|review|retry|reconcile|export-feedback|release|intake``.

These are deterministic handlers, not model tools: the model cannot approve its own draft.
The persona comes from the active Hermes profile; the principal is the local OS account and
must appear in ``config/operators.json`` for that persona.

``personadesk`` (console script) runs the same handlers outside Hermes for tests and offline
labs, with ``--profile`` standing in for ``hermes -p``.
"""

from __future__ import annotations

import argparse
import getpass
import imaplib
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import intake, releases
from .evidence import load_fixture
from .feedback import export_feedback
from .paths import artifacts_dir, safe_child, workshop_root
from .permissions import (
    PermissionDenied,
    authorize_operator,
    load_operators,
    load_permissions,
    require_id,
)
from .store import STATE_DB_ENV, InvalidTransition, Store, open_store
from .tasks import WorkerFailed, locks_dir, reconcile, run_job


@dataclass
class CommandContext:
    root: Path
    profile: str | None
    store_factory: Callable[[], Store]
    principal: str
    hermes_bin: str
    out: Callable[[str], None] = print


def setup_parser(parser: argparse.ArgumentParser) -> None:
    subs = parser.add_subparsers(dest="pd_command")

    run = subs.add_parser("run", help="Create (idempotently) and run one bounded job")
    run.add_argument("--fixture", required=True)
    run.add_argument("--task", default="draft_reply")
    run.add_argument("--source-key", help="Stable source event key (default: fixture+task)")
    run.add_argument("--no-execute", action="store_true", help="Only create the queued job")

    status = subs.add_parser("status", help="Show one job or recent jobs")
    status.add_argument("job", nargs="?")
    status.add_argument("--limit", type=int, default=20)

    show = subs.add_parser("show", help="Show the latest draft for review")
    show.add_argument("job")

    review = subs.add_parser("review", help="Approve or reject the exact draft revision")
    review.add_argument("job")
    review.add_argument("--draft-hash", required=True)
    review.add_argument("--decision", choices=["approve", "reject"], required=True)
    review.add_argument("--edited-file", help="Workshop-relative file holding corrected text")
    review.add_argument("--reason")
    review.add_argument("--learning-consent", action="store_true")

    retry = subs.add_parser("retry", help="Re-queue a failed job and run it again")
    retry.add_argument("job")

    rec = subs.add_parser("reconcile", help="Resolve a job left running by a crash")
    rec.add_argument("job")

    subs.add_parser("export-feedback", help="Export consented dev-split reviews (JSONL)")

    rel = subs.add_parser("release", help="Inspect, promote, or roll back persona releases")
    rel.add_argument("action", choices=["list", "active", "promote", "rollback"])
    rel.add_argument("release_id", nargs="?")

    intake_p = subs.add_parser("intake", help="Turn unseen local mail into jobs (mailsim)")
    intake_p.add_argument("--run", action="store_true", help="Also run each new job")
    intake_p.add_argument("--limit", type=int, default=10)
    intake_p.add_argument("--imap-host", help="Default: config/mailboxes.json")
    intake_p.add_argument("--imap-port", type=int, help="Default: config/mailboxes.json")


def _emit(cc: CommandContext, payload: Any) -> None:
    cc.out(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _authorized(cc: CommandContext):
    permissions = load_permissions(cc.root)
    grant = permissions.for_profile(cc.profile)
    authorize_operator(load_operators(cc.root), cc.principal, grant.client_id)
    return permissions, grant


def _owned_job(store: Store, job_id: str, client_id: str) -> dict[str, Any]:
    job = store.get_job(job_id)
    if job["client_id"] != client_id:
        raise PermissionDenied("Job belongs to a different persona.")
    return job


def _create_job(cc: CommandContext, store: Store, grant, fixture_id: str, task: str,
                source_key: str) -> tuple[dict[str, Any], bool]:
    active = releases.active_release(cc.root, grant.client_id)
    return store.create_job(
        source_key=source_key, principal=cc.principal, client_id=grant.client_id,
        profile=grant.hermes_profile, fixture_id=fixture_id, task=task,
        release_id=active["release_id"] if active else None,
    )


def dispatch(cc: CommandContext, args: argparse.Namespace) -> int:
    try:
        return _dispatch(cc, args)
    except (PermissionDenied, InvalidTransition, WorkerFailed, releases.ReleaseError,
            ValueError, KeyError, OSError, imaplib.IMAP4.error) as exc:
        _emit(cc, {"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 2


def _dispatch(cc: CommandContext, args: argparse.Namespace) -> int:
    command = getattr(args, "pd_command", None)
    if command is None:
        cc.out("Usage: personadesk {run,status,show,review,retry,reconcile,"
               "export-feedback,release,intake} ...")
        return 1
    permissions, grant = _authorized(cc)
    store = cc.store_factory()
    lock_dir = locks_dir(cc.root)

    if command == "run":
        grant.require("task", args.task)
        fixture = load_fixture(cc.root, grant, args.fixture)
        source_key = args.source_key or (
            f"manual:{grant.client_id}:{fixture.id}:v{fixture.data['version']}:{args.task}"
        )
        if len(source_key) > permissions.max_task_chars:
            raise ValueError("source key too long.")
        job, created = _create_job(cc, store, grant, fixture.id, args.task, source_key)
        if created and not args.no_execute:
            job = run_job(store=store, job=job, grant=grant, permissions=permissions,
                          hermes_bin=cc.hermes_bin, lock_dir=lock_dir)
        _emit(cc, {"ok": job["status"] != "failed", "created": created, "job": job,
                   "draft": _review_view(store.latest_draft(job["job_id"]))})
        return 0 if job["status"] != "failed" else 3

    if command == "intake":
        grant.require("task", "draft_reply")
        items = intake.fetch_unseen(cc.root, grant, limit=args.limit, host=args.imap_host,
                                    port=args.imap_port)
        results, consumed = [], []
        try:
            for item in items:
                consumed.append(item.uid)
                if item.rejected:
                    results.append({"uid": int(item.uid), "from": item.sender,
                                    "rejected": item.rejected})
                    continue
                fixture_id = item.fixture["id"]
                # Keep the first copy so a re-read never changes the fixture's content hash.
                if not (cc.root / intake.INBOX_RELATIVE / grant.client_id
                        / f"{fixture_id}.json").is_file():
                    intake.write_fixture(cc.root, item.fixture)
                source_key = f"mail:{grant.client_id}:{item.message_id}"[
                    :permissions.max_task_chars]
                job, created = _create_job(cc, store, grant, fixture_id, "draft_reply",
                                           source_key)
                if created and args.run:
                    job = run_job(store=store, job=job, grant=grant, permissions=permissions,
                                  hermes_bin=cc.hermes_bin, lock_dir=lock_dir)
                results.append({"uid": int(item.uid), "from": item.sender,
                                "subject": item.fixture["subject"], "fixture_id": fixture_id,
                                "created": created, "job_id": job["job_id"],
                                "status": job["status"]})
        finally:
            intake.mark_seen(cc.root, grant, consumed, host=args.imap_host,
                             port=args.imap_port)
        _emit(cc, {"ok": True, "processed": len(results), "items": results,
                   "note": "Drafts wait for `review`; nothing is sent."})
        return 0

    if command == "status":
        if args.job:
            _emit(cc, _owned_job(store, args.job, grant.client_id))
        else:
            _emit(cc, [j for j in store.list_jobs(args.limit)
                       if j["client_id"] == grant.client_id])
        return 0

    if command == "show":
        job = _owned_job(store, args.job, grant.client_id)
        _emit(cc, {"job": job, "draft": _review_view(store.latest_draft(job["job_id"]))})
        return 0

    if command == "review":
        _owned_job(store, args.job, grant.client_id)
        edited = None
        if args.edited_file:
            edited = safe_child(cc.root, *Path(args.edited_file).parts).read_text("utf-8")
        review = store.record_review(
            job_id=args.job, reviewer=cc.principal, presented_hash=args.draft_hash,
            decision=args.decision, edited_text=edited, reason=args.reason,
            learning_consent=args.learning_consent,
        )
        _emit(cc, {"ok": True, "review": review, "job": store.get_job(args.job),
                   "note": "Approved means approved as a sandbox draft; nothing was sent."})
        return 0

    if command == "retry":
        job = _owned_job(store, args.job, grant.client_id)
        store.transition(job["job_id"], "queued")
        job = run_job(store=store, job=store.get_job(job["job_id"]), grant=grant,
                      permissions=permissions, hermes_bin=cc.hermes_bin, lock_dir=lock_dir)
        _emit(cc, {"ok": job["status"] != "failed", "job": job})
        return 0 if job["status"] != "failed" else 3

    if command == "reconcile":
        _owned_job(store, args.job, grant.client_id)
        _emit(cc, reconcile(store, args.job, lock_dir))
        return 0

    if command == "export-feedback":
        out = artifacts_dir(cc.root) / "feedback" / f"{grant.client_id}.jsonl"
        _emit(cc, export_feedback(store, cc.root, grant, out))
        return 0

    if command == "release":
        if args.action == "list":
            _emit(cc, releases.list_releases(cc.root, grant.client_id))
        elif args.action == "active":
            _emit(cc, releases.active_release(cc.root, grant.client_id))
        elif args.action == "promote":
            release_id = require_id(args.release_id, "release_id")
            _emit(cc, releases.promote(cc.root, grant.client_id, release_id, cc.principal))
        else:
            _emit(cc, releases.rollback(cc.root, grant.client_id, cc.principal))
        return 0
    raise ValueError(f"Unknown command {command}")


def _review_view(draft: dict[str, Any] | None) -> dict[str, Any] | None:
    if draft is None:
        return None
    keys = ("draft_id", "revision", "body", "evidence", "uncertainties", "blocked_actions",
            "writer", "artifact_hash")
    return {k: draft[k] for k in keys}


def main(argv: list[str] | None = None) -> int:
    """Standalone entry point (no Hermes): ``personadesk --profile pd-priya run ...``."""
    parser = argparse.ArgumentParser(prog="personadesk", description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile", required=True, help="Persona profile (as in hermes -p)")
    parser.add_argument("--root", help="Workshop root (default: auto-detect)")
    parser.add_argument("--state-db", help="SQLite path (default: artifacts/state/<profile>.db)")
    parser.add_argument("--hermes-bin", default=os.environ.get("PERSONADESK_HERMES_BIN",
                                                               "hermes"))
    setup_parser(parser)
    args = parser.parse_args(argv)
    root = workshop_root(args.root)
    db = Path(args.state_db) if args.state_db else (
        artifacts_dir(root) / "state" / f"{require_id(args.profile, 'profile')}.db"
    )
    os.environ[STATE_DB_ENV] = str(db.resolve())  # child workers; Hermes reads the job binding
    cc = CommandContext(root=root, profile=args.profile, store_factory=lambda: open_store(db),
                        principal=getpass.getuser(), hermes_bin=args.hermes_bin)
    return dispatch(cc, args)


if __name__ == "__main__":
    sys.exit(main())
