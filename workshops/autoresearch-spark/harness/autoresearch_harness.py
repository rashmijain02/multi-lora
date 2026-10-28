"""Guard rails for an autoresearch loop: the agent proposes, this harness grades.

The agent (Hermes) may only edit ``train.py`` and commit. This harness:

* ``init``    applies the tier's fixed constants, commits the setup, and locks the
              metric files (sha256 + read-only).
* ``run``     verifies the lock and the edit scope, trains once with a timeout,
              parses the summary, logs ``results.tsv``, and keeps or reverts the commit.
* ``heldout`` re-trains the baseline and best commits in throwaway worktrees whose
              ``prepare.py`` evaluates on the held-back test split instead of val.
* ``status``  prints the results table and the current best.

Standard library only so it runs unchanged on Windows (light tier) and DGX Spark.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

WORKSHOP_DIR = Path(__file__).resolve().parent.parent
PROGRAM_TEMPLATE = WORKSHOP_DIR / "program.md"
DEFAULT_RUNS_DIR = WORKSHOP_DIR / "runs"

LOCKED_FILES = ("prepare.py", "pyproject.toml", "uv.lock")
EDITABLE_FILES = frozenset({"train.py"})
IGNORED_OUTPUTS = ("checkpoint_pre_eval.pt", "run.log", "results.tsv")
RESULTS_HEADER = (
    "commit", "val_bpb", "memory_gb", "num_steps", "training_s", "status", "description",
)

# Fixed (prepare.py) constants and the human-chosen starting point (train.py) per tier.
# Scores are only comparable inside one tier: budget, context and eval size differ.
TIERS: dict[str, dict] = {
    "light": {
        "prepare": {"TIME_BUDGET": "120", "MAX_SEQ_LEN": "512", "EVAL_TOKENS": "4 * 524288"},
        "train": {"DEPTH": "4", "TOTAL_BATCH_SIZE": "2 ** 16", "WINDOW_PATTERN": '"L"'},
        "timeout_s": 900,
    },
    "spark": {
        "prepare": {"TIME_BUDGET": "300"},
        "train": {"DEPTH": "4", "TOTAL_BATCH_SIZE": "2 ** 17"},
        "timeout_s": 1500,
    },
}

SUMMARY_KEYS = {
    "val_bpb": float,
    "training_seconds": float,
    "total_seconds": float,
    "peak_vram_mb": float,
    "num_steps": int,
    "num_params_M": float,
    "total_tokens_M": float,
}


class HarnessError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Pure helpers (unit tested)
# ---------------------------------------------------------------------------

def set_constants(source: str, values: dict[str, str]) -> str:
    """Rewrite top-level ``NAME = value`` lines, keeping any trailing comment."""
    for name, value in values.items():
        pattern = re.compile(rf"^({re.escape(name)}\s*=\s*)([^#\n]*?)(\s*#.*)?$", re.MULTILINE)
        source, count = pattern.subn(
            lambda m, v=value: f"{m.group(1)}{v}{m.group(3) or ''}", source
        )
        if count != 1:
            raise HarnessError(f"expected exactly one top-level '{name} =' line, found {count}")
    return source


def read_constant(source: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\s*=\s*([^#\n]+)", source, re.MULTILINE)
    if not match:
        raise HarnessError(f"constant {name} not found")
    return match.group(1).strip()


def parse_summary(log: str) -> dict | None:
    """Parse the last ``---`` summary block printed by train.py; None if the run crashed."""
    lines = log.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if not starts:
        return None
    found: dict = {}
    for line in lines[starts[-1] + 1:]:
        key, sep, raw = line.partition(":")
        key = key.strip()
        if sep and key in SUMMARY_KEYS:
            try:
                found[key] = SUMMARY_KEYS[key](raw.strip())
            except ValueError:
                continue
    return found if "val_bpb" in found else None


def decide(val_bpb: float | None, best: float | None, min_delta: float = 0.0) -> str:
    """keep / discard / crash. The first successful run is the baseline and is kept."""
    if val_bpb is None:
        return "crash"
    if best is None or val_bpb < best - min_delta:
        return "keep"
    return "discard"


def out_of_scope(changed: list[str]) -> list[str]:
    return sorted(p for p in changed if p not in EDITABLE_FILES)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def point_val_at_test(prepare_source: str) -> str:
    """Return prepare.py source whose 'val' split reads the held-back 'test' range."""
    test = re.search(r'"test"\s*:\s*(\([^)]*\))', prepare_source)
    val = re.search(r'"val"\s*:\s*\([^)]*\)', prepare_source)
    if not test or not val:
        raise HarnessError("prepare.py has no 'test' and 'val' split tuples; cannot run held-out")
    return prepare_source[: val.start()] + f'"val": {test.group(1)}' + prepare_source[val.end():]


def tsv_escape(text: str) -> str:
    return " ".join(text.replace("\t", " ").split())


# ---------------------------------------------------------------------------
# Git / filesystem plumbing
# ---------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False
    )
    if proc.returncode != 0:
        raise HarnessError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")


def dirty_paths(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    # -z entries are "XY path"; renames add the source path as a separate entry.
    return [entry[3:] for entry in out.split("\0") if len(entry) > 3]


def set_read_only(path: Path, read_only: bool) -> None:
    mode = path.stat().st_mode
    if read_only:
        path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    else:
        path.chmod(mode | stat.S_IWUSR)


@dataclass
class State:
    path: Path
    data: dict

    @classmethod
    def load(cls, state_dir: Path) -> State:
        path = state_dir / "state.json"
        if not path.exists():
            raise HarnessError(f"no state at {path}; run 'init' first")
        return cls(path, json.loads(path.read_text(encoding="utf-8")))

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")


def append_result(state_dir: Path, row: dict) -> None:
    results = state_dir / "results.tsv"
    if not results.exists():
        results.write_text("\t".join(RESULTS_HEADER) + "\n", encoding="utf-8")
    with results.open("a", encoding="utf-8") as fh:
        fh.write("\t".join(str(row.get(col, "")) for col in RESULTS_HEADER) + "\n")


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the run and its children (uv spawns python, which holds the GPU)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
    else:
        import signal

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.kill()
    proc.wait()


def train_once(repo: Path, run_cmd: list[str], timeout_s: int, log_path: Path,
               env_extra: dict | None = None) -> tuple[str, bool]:
    """Run training, streaming to log_path. Returns (log text, timed_out)."""
    env = {**os.environ, **(env_extra or {})}
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.Popen(run_cmd, cwd=repo, stdout=log, stderr=subprocess.STDOUT, env=env,
                                start_new_session=os.name != "nt")
        try:
            proc.wait(timeout=timeout_s)
            timed_out = False
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            timed_out = True
    return log_path.read_text(encoding="utf-8", errors="replace"), timed_out


def check_lock(repo: Path, lock: dict) -> list[str]:
    return [name for name, digest in lock.items()
            if not (repo / name).exists() or sha256_file(repo / name) != digest]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    repo = Path(args.upstream).resolve()
    tier = TIERS[args.tier]
    state_root = Path(args.state_dir).resolve()
    state_dir = state_root / args.tag
    if (state_dir / "state.json").exists():
        raise HarnessError(f"{state_dir} already initialised; pick a new --tag")

    # `uv sync` may rewrite uv.lock; that setup change is committed with the tier setup.
    stray = [p for p in dirty_paths(repo) if p not in ("uv.lock",) + IGNORED_OUTPUTS]
    if stray:
        raise HarnessError(f"upstream has uncommitted changes: {stray}")

    for key, value in (("user.name", "autoresearch-agent"),
                       ("user.email", "agent@example.invalid")):
        if subprocess.run(["git", "config", key], cwd=repo, capture_output=True,
                          check=False).returncode:
            git(repo, "config", "--local", key, value)

    branch = f"autoresearch/{args.tag}"
    git(repo, "checkout", "-q", "-b", branch)

    prepare = repo / "prepare.py"
    set_read_only(prepare, False)
    prepare.write_text(set_constants(prepare.read_text(encoding="utf-8"), tier["prepare"]),
                       encoding="utf-8")
    train = repo / "train.py"
    train.write_text(set_constants(train.read_text(encoding="utf-8"), tier["train"]),
                     encoding="utf-8")

    budget_s = int(read_constant(prepare.read_text(encoding="utf-8"), "TIME_BUDGET"))
    timeout_s = args.timeout_s or tier["timeout_s"]
    harness_cmd = (f'uv run --no-project python "{Path(__file__).resolve()}" '
                   f'--state-dir "{state_root}"')
    program = PROGRAM_TEMPLATE.read_text(encoding="utf-8")
    for key, value in {
        "{{TIER}}": args.tier,
        "{{TAG}}": args.tag,
        "{{BUDGET_MIN}}": f"{budget_s / 60:g}",
        "{{TIMEOUT_MIN}}": f"{timeout_s / 60:g}",
        "{{HARNESS}}": harness_cmd,
    }.items():
        program = program.replace(key, value)
    (repo / "program.md").write_text(program, encoding="utf-8")

    gitignore = repo / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    lines += [p for p in IGNORED_OUTPUTS if p not in lines]
    gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")

    git(repo, "add", "-u")
    git(repo, "add", "program.md", ".gitignore")
    git(repo, "commit", "-q", "-m", f"workshop: {args.tier} tier setup ({args.tag})")

    state_dir.mkdir(parents=True, exist_ok=True)
    lock = {name: sha256_file(repo / name) for name in LOCKED_FILES if (repo / name).exists()}
    set_read_only(prepare, True)
    State(state_dir / "state.json", {
        "tier": args.tier,
        "tag": args.tag,
        "upstream": str(repo),
        "branch": branch,
        "base_commit": head(repo),
        "best_commit": None,
        "best_val_bpb": None,
        "baseline_commit": None,
        "lock": lock,
        "run_cmd": args.run_cmd.split() if args.run_cmd else ["uv", "run", "train.py"],
        # The agent's shell may not inherit this, so every training run gets it explicitly.
        "env": {k: os.environ[k] for k in ("AUTORESEARCH_CACHE_DIR",) if k in os.environ},
        "timeout_s": timeout_s,
        "min_delta": args.min_delta,
        "runs": 0,
    }).save()
    print(f"initialised {args.tier} tier on {branch}; locked {', '.join(lock)}")
    print(f"state: {state_dir}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve() / args.tag
    state = State.load(state_dir)
    s = state.data
    repo = Path(s["upstream"])
    anchor = s["best_commit"] or s["base_commit"]

    tampered = check_lock(repo, s["lock"])
    if tampered:
        print(f"REFUSED: locked files changed: {tampered}. Restore them; the metric is not "
              "yours to edit.")
        return 2
    if git(repo, "rev-parse", "--abbrev-ref", "HEAD") != s["branch"]:
        print(f"REFUSED: not on {s['branch']}")
        return 2
    pending = [p for p in dirty_paths(repo) if p not in IGNORED_OUTPUTS]
    if pending:
        print(f"REFUSED: commit your train.py change first; uncommitted: {pending}")
        return 2
    if s["best_commit"] is not None and head(repo) == anchor:
        print("REFUSED: nothing new to test; commit a train.py change first")
        return 2
    bad = out_of_scope(git(repo, "diff", "--name-only", anchor, "HEAD").splitlines())
    if bad:
        git(repo, "reset", "-q", "--hard", anchor)
        print(f"REFUSED and reverted: only train.py may change, but you touched {bad}")
        return 2

    commit = head(repo)
    log_path = state_dir / f"run_{s['runs'] + 1:03d}.log"
    started = time.monotonic()
    log, timed_out = train_once(repo, s["run_cmd"], s["timeout_s"], log_path, s.get("env"))
    wall_s = time.monotonic() - started
    summary = None if timed_out else parse_summary(log)
    val = summary["val_bpb"] if summary else None
    status = decide(val, s["best_val_bpb"], s["min_delta"])
    if timed_out:
        reason = f"timeout>{s['timeout_s']}s"
    elif "OutOfMemoryError" in log or "CUDA out of memory" in log:
        reason = "OOM"
    else:
        reason = ""

    summary = summary or {}
    append_result(state_dir, {
        "commit": commit[:7],
        "val_bpb": f"{val:.6f}" if val is not None else "0.000000",
        "memory_gb": f"{summary.get('peak_vram_mb', 0.0) / 1024:.1f}",
        "num_steps": summary.get("num_steps", 0),
        "training_s": f"{summary.get('training_seconds', 0.0):.1f}",
        "status": status,
        "description": tsv_escape(args.description + (f" [{reason}]" if reason else "")),
    })

    s["runs"] += 1
    if status == "keep":
        if s["best_commit"] is None:
            s["baseline_commit"] = commit
        s["best_commit"], s["best_val_bpb"] = commit, val
    else:
        git(repo, "reset", "-q", "--hard", anchor)
    state.save()

    best = s["best_val_bpb"]
    print(f"{status.upper()}: val_bpb={'crash' if val is None else f'{val:.6f}'} "
          f"best={'none' if best is None else f'{best:.6f}'} wall={wall_s:.0f}s log={log_path}")
    if status != "keep":
        print(f"branch reset to {anchor[:7]}")
    if status == "crash":
        print("--- last 30 log lines ---\n" + "\n".join(log.splitlines()[-30:]))
    return 0


def cmd_heldout(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve() / args.tag
    s = State.load(state_dir).data
    repo = Path(s["upstream"])
    if not s["best_commit"]:
        raise HarnessError("no kept runs yet")
    if check_lock(repo, s["lock"]):
        raise HarnessError("locked files changed; refusing to evaluate")
    test_prepare = point_val_at_test((repo / "prepare.py").read_text(encoding="utf-8"))

    rows = []
    for label, commit in (("baseline", s["baseline_commit"]), ("best", s["best_commit"])):
        work = Path(tempfile.mkdtemp(prefix=f"heldout_{label}_"))
        shutil.rmtree(work)
        try:
            git(repo, "worktree", "add", "-q", "--detach", str(work), commit)
            target = work / "prepare.py"
            set_read_only(target, False)
            target.write_text(test_prepare, encoding="utf-8")
            log, timed_out = train_once(work, s["run_cmd"], s["timeout_s"],
                                        state_dir / f"heldout_{label}.log", s.get("env"))
            summary = None if timed_out else parse_summary(log)
            rows.append((label, commit[:7], summary["val_bpb"] if summary else None))
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(work)], cwd=repo,
                           capture_output=True, check=False)
            shutil.rmtree(work, ignore_errors=True)

    out = state_dir / "heldout.tsv"
    with out.open("w", encoding="utf-8") as fh:
        fh.write("label\tcommit\ttest_bpb\n")
        for label, commit, value in rows:
            fh.write(f"{label}\t{commit}\t{'crash' if value is None else f'{value:.6f}'}\n")
    print(out.read_text(encoding="utf-8"), end="")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state_dir = Path(args.state_dir).resolve() / args.tag
    s = State.load(state_dir).data
    results = state_dir / "results.tsv"
    if results.exists():
        print(results.read_text(encoding="utf-8"), end="")
    print(f"tier={s['tier']} runs={s['runs']} best={s['best_val_bpb']} "
          f"best_commit={(s['best_commit'] or '')[:7]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Guard rails for an autoresearch loop.")
    parser.add_argument("--state-dir", default=os.environ.get("AUTORESEARCH_STATE_DIR",
                                                               str(DEFAULT_RUNS_DIR)))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="apply tier constants, commit setup, lock the metric")
    p.add_argument("--upstream", required=True, help="path to the autoresearch clone")
    p.add_argument("--tier", choices=sorted(TIERS), required=True)
    p.add_argument("--tag", required=True, help="run tag, e.g. light-sep14")
    p.add_argument("--timeout-s", type=int, default=None)
    p.add_argument("--min-delta", type=float, default=0.0,
                   help="required val_bpb improvement to keep a change")
    p.add_argument("--run-cmd", default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_init)

    for name, func, help_text in (
        ("run", cmd_run, "train the committed change once, then keep or revert it"),
        ("heldout", cmd_heldout, "score baseline and best on the held-back test split"),
        ("status", cmd_status, "show results and the current best"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--tag", required=True)
        if name == "run":
            p.add_argument("--description", required=True)
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
