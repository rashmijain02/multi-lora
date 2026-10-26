"""Deterministic stand-in for ``hermes -p <profile> chat --oneshot ... --format stream-json``.

It loads the real PersonaDesk tool handlers in-process (as Hermes would), follows the
documented worker steps without a language model, and prints Hermes-style JSONL events.
Use it to learn the job pipeline (E0) and to test failure handling:

    PERSONADESK_HERMES_BIN=scripts/fake_hermes.py personadesk --profile pd-priya run --fixture priya-001

``FAKE_HERMES_MODE``: ok (default) | no_result | error | nonzero | sleep | no_draft | malformed.
``PERSONADESK_WRITER_BACKEND``: template (default) | http.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hermes_plugin.paths import workshop_root
from hermes_plugin.store import open_store
from hermes_plugin.tools import Runtime, make_handlers


def emit(event: dict) -> None:
    print(json.dumps({"timestamp": int(time.time() * 1000), **event}), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--profile", required=True)
    parser.add_argument("command", choices=["chat"])
    parser.add_argument("--oneshot", action="store_true")
    parser.add_argument("--query-file", required=True)
    parser.add_argument("--format", choices=["stream-json"], required=True)
    parser.add_argument("--toolsets")
    parser.add_argument("--max-turns", type=int, default=4)
    args = parser.parse_args()
    mode = os.environ.get("FAKE_HERMES_MODE", "ok")
    session_id = "fake-session-" + str(os.getpid())
    emit({"type": "system", "subtype": "init", "model": "fake-controller",
          "session_id": session_id})
    if mode == "sleep":
        time.sleep(3600)
    if mode == "malformed":
        print("this is not json", flush=True)
        return 1
    query = Path(args.query_file).read_text(encoding="utf-8")
    match = re.search(r"^Fixture ID: ([a-z0-9-]+)$", query, re.MULTILINE)
    if not match:
        emit({"type": "result", "session_id": session_id, "exit_code": 1, "text": "",
              "error": "no fixture id in query"})
        return 1
    fixture_id = match.group(1)
    token = re.search(r"^Job token: (\S+)$", query, re.MULTILINE)
    job_token = token.group(1) if token else ""
    runtime = Runtime(
        root=workshop_root(None),
        settings={"writer_backend": os.environ.get("PERSONADESK_WRITER_BACKEND", "template"),
                  "writer_url": os.environ.get("PERSONADESK_WRITER_URL",
                                               "http://127.0.0.1:8100")},
        profile_name=lambda: args.profile,
        store_factory=open_store,
    )
    tools = make_handlers(runtime)
    grant = runtime.grant()
    turns = 0

    def call(name: str, tool_args: dict) -> dict:
        nonlocal turns
        turns += 1
        emit({"type": "tool_use", "name": name, "input": tool_args})
        started = time.perf_counter()
        output = tools[name](tool_args)
        result = json.loads(output)
        emit({"type": "tool_result", "name": name, "output": output[:5000],
              "duration_ms": int((time.perf_counter() - started) * 1000),
              "is_error": not result.get("ok", False)})
        return result

    call("pd_read_fixture", {"fixture_id": fixture_id})
    for check in grant.checks:
        call("pd_run_check", {"check": check, "fixture_id": fixture_id})
    if mode != "no_draft":
        draft = call("pd_draft_reply", {"fixture_id": fixture_id, "job_token": job_token})
    else:
        draft = {"ok": True, "body": ""}
    if mode == "error" or not draft.get("ok"):
        emit({"type": "result", "session_id": session_id, "exit_code": 1, "text": "",
              "error": draft.get("message", "forced error")})
        return 1
    if mode == "no_result":
        return 0
    code = 1 if mode == "nonzero" else 0
    emit({"type": "result", "session_id": session_id, "exit_code": code,
          "text": f"Draft stored ({turns} tool calls).",
          "tokens": {"input": 0, "output": 0, "total": 0}, "duration_ms": 0})
    return code


if __name__ == "__main__":
    sys.exit(main())
