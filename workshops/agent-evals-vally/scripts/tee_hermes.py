"""Stand in front of the Hermes worker and copy its stream-json output to a file.

PersonaDesk's ``run_job`` launches the worker as ``<hermes_bin> -p <profile> chat ...`` and
reads its stdout only after it exits. Vally needs the same lines, including the partial
stream when a trial hits its time limit, so this wrapper relays every line to stdout
unchanged *and* appends it to ``PD_EVAL_STREAM_FILE`` as it arrives.

    PD_EVAL_REAL_HERMES     the real worker (``hermes`` or ``.../fake_hermes.py``)
    PD_EVAL_STREAM_FILE     where to append the raw JSONL lines
    PD_EVAL_WORKER_TIMEOUT  optional seconds; on expiry the worker's process tree is
                            killed and ``<stream file>.timeout`` is created

Enforcing the limit here, not by killing PersonaDesk, lets ``run_job`` see a worker that
ended without a result, mark the job failed, and release its lock and job binding.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from _personadesk import import_personadesk

EXIT_TIMEOUT = 124


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        os.killpg(proc.pid, signal.SIGKILL)


def main() -> int:
    import_personadesk()
    from hermes_plugin.tasks import worker_command

    real = os.environ.get("PD_EVAL_REAL_HERMES")
    stream_file = os.environ.get("PD_EVAL_STREAM_FILE")
    if not real or not stream_file:
        print("PD_EVAL_REAL_HERMES and PD_EVAL_STREAM_FILE must be set.", file=sys.stderr)
        return 2
    timeout = float(os.environ.get("PD_EVAL_WORKER_TIMEOUT") or 0) or None
    argv = [*worker_command(real), *sys.argv[1:]]
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        start_new_session=os.name != "nt",
    )

    def relay() -> None:
        assert proc.stdout is not None
        with open(stream_file, "a", encoding="utf-8") as sink:
            for line in proc.stdout:
                sink.write(line)
                sink.flush()
                sys.stdout.write(line)
                sys.stdout.flush()

    reader = threading.Thread(target=relay, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        proc.wait()
        reader.join(timeout=5)
        Path(stream_file + ".timeout").write_text(f"{timeout}\n", encoding="utf-8")
        print(f"worker stopped after {timeout} s", file=sys.stderr)
        return EXIT_TIMEOUT
    reader.join(timeout=5)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
