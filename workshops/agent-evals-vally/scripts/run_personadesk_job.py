"""Run one PersonaDesk job exactly as production does, for one Vally trial.

The Vally executor calls this once per trial. It does not reimplement the job pipeline: it
calls PersonaDesk's own ``run_job`` (lock, one-time job token, ``hermes ... --format
stream-json``, result judgement, persisted draft). Only two things differ from
``personadesk run``:

* the job store is a fresh SQLite file inside the trial's output directory, so trials never
  share drafts; and
* the worker is launched through ``tee_hermes.py``, which records the raw event stream.

Outputs, all under ``--out-dir``:

    state.db       the trial's PersonaDesk job store
    stream.jsonl   raw Hermes stream-json lines (kept when the worker hits its time limit)
    stream.jsonl.timeout   present only if tee_hermes.py stopped the worker at the limit
    job.json       final job record plus the stored draft (the reviewed artifact)
    draft.txt      the stored draft body, for simple file graders; written ONLY when the job
                   reached awaiting_review, because a failed job's leftover draft is never
                   shown to a reviewer (job.json still records it for diagnosis)

Exit codes: 0 job awaiting review; 1 job failed (an agent outcome, still graded);
75 temporary infrastructure problem (lock busy; Vally may retry);
78 configuration problem (unknown profile or fixture, missing Hermes).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from _personadesk import import_personadesk

EXIT_AGENT_FAILED = 1
EXIT_TEMPFAIL = 75
EXIT_CONFIG = 78


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", required=True, help="Hermes profile, e.g. pd-priya")
    parser.add_argument("--fixture", required=True, help="Fixture ID, e.g. priya-002")
    parser.add_argument("--task", default="draft_reply")
    parser.add_argument("--hermes-bin", required=True,
                        help="'hermes', or a path to scripts/fake_hermes.py")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=0,
                        help="Agent time limit enforced by tee_hermes.py (0 = PersonaDesk's own)")
    args = parser.parse_args()

    root = import_personadesk()
    from hermes_plugin import releases
    from hermes_plugin.evidence import load_fixture
    from hermes_plugin.permissions import PermissionDenied, load_permissions
    from hermes_plugin.store import open_store
    from hermes_plugin.tasks import WorkerFailed, locks_dir, run_job

    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    stream_file = out / "stream.jsonl"
    stream_file.write_text("", encoding="utf-8")
    Path(str(stream_file) + ".timeout").unlink(missing_ok=True)
    os.environ["PD_EVAL_REAL_HERMES"] = args.hermes_bin
    os.environ["PD_EVAL_STREAM_FILE"] = str(stream_file)
    if args.timeout_seconds > 0:
        os.environ["PD_EVAL_WORKER_TIMEOUT"] = str(args.timeout_seconds)

    def fail(code: int, kind: str, message: str) -> int:
        (out / "job.json").write_text(json.dumps({"ok": False, "error": kind,
                                                  "message": message}, indent=2),
                                      encoding="utf-8")
        print(f"{kind}: {message}", file=sys.stderr)
        return code

    try:
        permissions = load_permissions(root)
        grant = permissions.for_profile(args.profile)
        grant.require("task", args.task)
        fixture = load_fixture(root, grant, args.fixture)
    except (PermissionDenied, KeyError, ValueError, FileNotFoundError) as exc:
        return fail(EXIT_CONFIG, type(exc).__name__, str(exc))

    store = open_store(out / "state.db")
    active = releases.active_release(root, grant.client_id)
    job, _ = store.create_job(
        source_key=f"vally:{grant.client_id}:{fixture.id}:{args.task}:{uuid.uuid4().hex[:8]}",
        principal="vally-eval", client_id=grant.client_id, profile=grant.hermes_profile,
        fixture_id=fixture.id, task=args.task,
        release_id=active["release_id"] if active else None,
    )
    tee = Path(__file__).resolve().parent / "tee_hermes.py"
    try:
        job = run_job(store=store, job=job, grant=grant, permissions=permissions,
                      hermes_bin=str(tee), lock_dir=locks_dir(root))
    except WorkerFailed as exc:  # raised only before the worker starts: the lock is busy
        return fail(EXIT_TEMPFAIL, "lock_busy", str(exc))

    draft = store.latest_draft(job["job_id"])
    (out / "job.json").write_text(json.dumps({"ok": job["status"] == "awaiting_review",
                                              "job": job, "draft": draft},
                                             indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    if draft and job["status"] == "awaiting_review":
        (out / "draft.txt").write_text(draft["body"], encoding="utf-8")
    store.conn.close()
    if job["status"] == "failed" and str(job.get("error", "")).startswith(
            "Hermes executable not found"):
        return EXIT_CONFIG
    return 0 if job["status"] == "awaiting_review" else EXIT_AGENT_FAILED


if __name__ == "__main__":
    sys.exit(main())
