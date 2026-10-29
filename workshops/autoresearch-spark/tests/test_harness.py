import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import autoresearch_harness as h

# A venv launcher kills its children itself on Windows; use the real interpreter.
BASE_PYTHON = getattr(sys, "_base_executable", sys.executable)

FAKE_PREPARE = '''TIME_BUDGET = 300           # seconds
MAX_SEQ_LEN = 2048
EVAL_TOKENS = 40 * 524288
SPLITS = {
    "test": (0, 10_000),
    "val": (10_000, 20_000),
    "train": (20_000, None),
}
'''

# train.py prints a summary whose val_bpb is the SCORE constant, or crashes when SCORE < 0.
FAKE_TRAIN = '''import os
if os.environ.get("AUTORESEARCH_CACHE_DIR") != "cache-from-init":
    raise SystemExit("data cache not found")
DEPTH = 8
TOTAL_BATCH_SIZE = 2 ** 19
WINDOW_PATTERN = "SSSL"   # sliding window
SCORE = 1.5
if SCORE < 0:
    raise SystemExit("torch.OutOfMemoryError: CUDA out of memory")
print("step 00001 | loss 3.0")
print("---")
print(f"val_bpb:          {SCORE:.6f}")
print("training_seconds: 120.1")
print("peak_vram_mb:     2048.0")
print("num_steps:        321")
'''


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def upstream(tmp_path, monkeypatch):
    repo = tmp_path / "upstream"
    repo.mkdir()
    (repo / "prepare.py").write_text(FAKE_PREPARE)
    (repo / "train.py").write_text(FAKE_TRAIN)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\n")
    (repo / "uv.lock").write_text("version = 1\n")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "upstream")
    # `uv sync` rewrites uv.lock in a fresh clone; init must accept and commit that.
    (repo / "uv.lock").write_text("version = 1\nrevision = 3\n")
    state = tmp_path / "runs"
    monkeypatch.setenv("AUTORESEARCH_CACHE_DIR", "cache-from-init")
    rc = h.main(["--state-dir", str(state), "init", "--upstream", str(repo), "--tier", "light",
                 "--tag", "t1", "--run-cmd", f"{sys.executable} train.py"])
    assert rc == 0
    # The agent's shell may lack the variable; runs must still find the data.
    monkeypatch.delenv("AUTORESEARCH_CACHE_DIR")
    return repo, state


def _propose(repo, score, extra_file=None):
    path = repo / "train.py"
    path.write_text(h.set_constants(path.read_text(), {"SCORE": str(score)}))
    if extra_file:
        (repo / extra_file).write_text("x")
        _git(repo, "add", extra_file)
    _git(repo, "commit", "-qam", f"score {score}")


def _run(state, desc="idea"):
    return h.main(["--state-dir", str(state), "run", "--tag", "t1", "--description", desc])


def _results(state):
    lines = (state / "t1" / "results.tsv").read_text().splitlines()
    return [dict(zip(h.RESULTS_HEADER, line.split("\t"))) for line in lines[1:]]


def test_set_constants_keeps_comments_and_rejects_missing():
    out = h.set_constants(FAKE_TRAIN, {"WINDOW_PATTERN": '"L"', "DEPTH": "4"})
    assert 'WINDOW_PATTERN = "L"   # sliding window' in out
    assert "DEPTH = 4\n" in out
    with pytest.raises(h.HarnessError):
        h.set_constants(FAKE_TRAIN, {"NOT_THERE": "1"})


def test_parse_summary_uses_last_block_and_detects_crash():
    log = "---\nval_bpb: 9.0\nnoise\n---\nval_bpb:          1.234567\nnum_steps:        42\n"
    assert h.parse_summary(log) == {"val_bpb": 1.234567, "num_steps": 42}
    assert h.parse_summary("Traceback ...\nCUDA out of memory") is None


def test_point_val_at_test_swaps_only_val():
    out = h.point_val_at_test(FAKE_PREPARE)
    assert '"val": (0, 10_000)' in out
    assert '"train": (20_000, None)' in out


def test_init_applies_tier_and_locks_metric(upstream):
    repo, _state = upstream
    assert "TIME_BUDGET = 120           # seconds" in (repo / "prepare.py").read_text()
    assert "DEPTH = 4" in (repo / "train.py").read_text()
    program = (repo / "program.md").read_text()
    assert "2 minute" in program and "{{" not in program
    assert _git(repo, "status", "--porcelain") == ""


def test_keep_then_discard_resets_to_best(upstream):
    repo, state = upstream
    assert _run(state, "baseline") == 0
    best = _git(repo, "rev-parse", "HEAD")
    _propose(repo, 1.2)
    assert _run(state) == 0
    improved = _git(repo, "rev-parse", "HEAD")
    assert improved != best
    _propose(repo, 1.3)
    assert _run(state) == 0
    assert _git(repo, "rev-parse", "HEAD") == improved
    assert [r["status"] for r in _results(state)] == ["keep", "keep", "discard"]
    assert _results(state)[1]["num_steps"] == "321"


def test_crash_is_logged_with_reason_and_reverted(upstream):
    repo, state = upstream
    _run(state, "baseline")
    best = _git(repo, "rev-parse", "HEAD")
    _propose(repo, -1)
    assert _run(state, "too wide") == 0
    row = _results(state)[-1]
    assert row["status"] == "crash" and "[OOM]" in row["description"]
    assert _git(repo, "rev-parse", "HEAD") == best


def test_tampered_metric_is_refused(upstream):
    repo, state = upstream
    _run(state, "baseline")
    prepare = repo / "prepare.py"
    h.set_read_only(prepare, False)
    prepare.write_text(prepare.read_text() + "# easier eval\n")
    _git(repo, "commit", "-qam", "sneaky")
    assert _run(state) == 2
    assert len(_results(state)) == 1


def test_edit_outside_train_py_is_reverted(upstream):
    repo, state = upstream
    _run(state, "baseline")
    best = _git(repo, "rev-parse", "HEAD")
    _propose(repo, 1.0, extra_file="helper.py")
    assert _run(state) == 2
    assert _git(repo, "rev-parse", "HEAD") == best
    assert not (repo / "helper.py").exists()


def test_rerunning_best_commit_is_refused(upstream):
    _repo, state = upstream
    _run(state, "baseline")
    assert _run(state, "again") == 2


def test_hung_run_and_its_child_are_killed(tmp_path):
    marker = tmp_path / "child_alive.txt"
    child = tmp_path / "child.py"
    child.write_text(f"import time, pathlib\ntime.sleep(4)\npathlib.Path({str(marker)!r}).write_text('x')\n")
    script = tmp_path / "parent.py"
    # Parent spawns a child (like `uv` spawning python) and both hang past the timeout.
    script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, {str(child)!r}])\n"
        "time.sleep(60)\n"
    )
    _log, timed_out = h.train_once(tmp_path, [BASE_PYTHON, str(script)], 2, tmp_path / "l.log")
    assert timed_out
    time.sleep(4)
    assert not marker.exists()


def test_heldout_scores_on_test_split(upstream):
    repo, state = upstream
    _run(state, "baseline")
    _propose(repo, 1.1)
    _run(state)
    assert h.main(["--state-dir", str(state), "heldout", "--tag", "t1"]) == 0
    lines = (state / "t1" / "heldout.tsv").read_text().splitlines()
    assert lines[1].startswith("baseline") and lines[1].endswith("1.500000")
    assert lines[2].startswith("best") and lines[2].endswith("1.100000")
    assert _git(repo, "worktree", "list").count("\n") == 0
