"""Source-relative path discovery, Git-ignore checks, and private output permissions."""

import csv
import os
import re
import subprocess
import uuid
from pathlib import Path

WORKSHOP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = WORKSHOP_ROOT.parents[1]
INPUT_TREE_ROOT = WORKSHOP_ROOT / "input"
DATASET_FILENAME = "reply-conversations.jsonl"
DEFAULT_INPUT_DIR = INPUT_TREE_ROOT / "enron"
DEFAULT_OUTPUT_ROOT = WORKSHOP_ROOT / "output"


def display_path(path: Path) -> str:
    resolved = path.resolve()
    return str(resolved.relative_to(REPO_ROOT)) if resolved.is_relative_to(REPO_ROOT) else path.name


def ensure_unlinked_path(path: Path) -> Path:
    candidate = Path(os.path.normpath(str(path.absolute())))
    if candidate.resolve() != candidate:
        raise ValueError("Paths must not use symbolic links or junctions.")
    current = candidate
    while True:
        if current.exists() and current.resolve() != current:
            raise ValueError("Paths must not use symbolic links or junctions.")
        if current.parent == current:
            break
        current = current.parent
    return candidate


def restrict_directory(directory: Path) -> None:
    if os.name == "nt":
        identity = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
        )
        sid = next(csv.reader(identity.stdout.splitlines()))[1]
        if not re.fullmatch(r"S-\d+(?:-\d+)+", sid):
            raise ValueError("Cannot determine the current Windows user SID.")
        subprocess.run(
            ["icacls.exe", str(directory), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    else:
        directory.chmod(0o700)


def ensure_repo_output_ignored(output_root: Path) -> None:
    candidate = ensure_unlinked_path(output_root)
    if not candidate.is_relative_to(REPO_ROOT):
        return
    rel_posix = candidate.relative_to(REPO_ROOT).as_posix()
    probe = f"{rel_posix}/.ignore-probe" if rel_posix not in ("", ".") else ".ignore-probe"
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "--no-pager", "check-ignore", "-q", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"Custom in-repository output root '{rel_posix}' is not ignored by Git. "
            f"Add '/{rel_posix}/' to .gitignore or choose an ignored/external output directory."
        )


def _resolve_caller_path(value: str | Path, *, cwd: Path | None = None) -> Path:
    raw_str = str(value).strip()
    if not raw_str:
        raise ValueError("Directory path must not be empty.")
    raw = Path(raw_str)
    base = ensure_unlinked_path(cwd if cwd is not None else Path.cwd())
    joined = raw if raw.is_absolute() else (base / raw)
    return ensure_unlinked_path(joined)


def resolve_input_dir(
    input_dir: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> tuple[Path, Path]:
    directory = (
        ensure_unlinked_path(DEFAULT_INPUT_DIR)
        if input_dir is None
        else _resolve_caller_path(input_dir, cwd=cwd)
    )
    if not directory.exists() or not directory.is_dir():
        raise ValueError(f"Input directory does not exist: {display_path(directory)}")
    dataset_path = ensure_unlinked_path(directory / DATASET_FILENAME)
    if not dataset_path.is_file():
        raise ValueError(
            f"Prepared dataset '{DATASET_FILENAME}' not found in input directory: "
            f"{display_path(directory)}"
        )
    return directory, dataset_path


def _ensure_private_dir_chain(target: Path) -> Path:
    candidate = ensure_unlinked_path(target)
    if candidate.exists():
        if not candidate.is_dir():
            raise ValueError(f"Output path exists and is not a directory: {display_path(candidate)}")
        return candidate
    missing: list[Path] = []
    cursor = candidate
    while not cursor.exists():
        missing.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise ValueError(
                    f"Output path exists and is not a directory: {display_path(directory)}"
                ) from None
        else:
            restrict_directory(directory)
    return candidate


def prepare_output_root(
    output_dir: str | Path | None = None,
    *,
    cwd: Path | None = None,
    input_dir: Path | None = None,
) -> Path:
    root = (
        ensure_unlinked_path(DEFAULT_OUTPUT_ROOT)
        if output_dir is None
        else _resolve_caller_path(output_dir, cwd=cwd)
    )
    protected_inputs = [ensure_unlinked_path(INPUT_TREE_ROOT)]
    if input_dir is not None:
        protected_inputs.append(ensure_unlinked_path(input_dir))
    for protected in protected_inputs:
        if root == protected or root.is_relative_to(protected) or protected.is_relative_to(root):
            raise ValueError("Output directory must not overlap an input directory.")
    ensure_repo_output_ignored(root)
    try:
        created = _ensure_private_dir_chain(root)
        probe = created / f".write-probe-{uuid.uuid4().hex[:8]}"
        with probe.open("x", encoding="utf-8") as handle:
            handle.write("ok")
        probe.unlink()
    except OSError as error:
        raise ValueError(f"Output directory is not writable ({display_path(root)}): {error}") from error
    return created


def prepare_stage_dir(output_root: Path, stage: str) -> Path:
    if stage not in ("baseline", "sft", "grpo"):
        raise ValueError(f"Unsupported output stage '{stage}'.")
    root = ensure_unlinked_path(output_root)
    ensure_repo_output_ignored(root)
    stage_dir = ensure_unlinked_path(root / stage)
    for directory in (root, stage_dir):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            if not directory.is_dir():
                raise
        else:
            restrict_directory(directory)
    return stage_dir


def create_stage_run_dir(output_root: Path, stage: str, *, smoke: bool = False) -> Path:
    stage_dir = prepare_stage_dir(output_root, stage)
    prefix = "smoke" if smoke else "run"
    run_dir = ensure_unlinked_path(stage_dir / f"{prefix}-{uuid.uuid4().hex[:12]}")
    run_dir.mkdir(mode=0o700, exist_ok=False)
    restrict_directory(run_dir)
    return run_dir
