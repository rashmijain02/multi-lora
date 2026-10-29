"""Paths, JSONL I/O and the sealed gold set (PersonaDesk fixtures).

Every path a learner passes is resolved against the workshop root, so commands behave the same
from any working directory and never embed a checkout location.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from slm_router.labels import PERSONAS, canonical

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT.parent / "personal-agent-multilora" / "fixtures"


def workshop_path(value: str | Path) -> Path:
    """Resolve a learner-supplied path relative to the workshop root; refuse absolute paths."""
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"use a path relative to workshops/slm-task-models: {value}")
    return ROOT / path


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gold(fixtures: Path = FIXTURES) -> list[dict]:
    """Return every PersonaDesk fixture as a router row; labels are ``expected.required_checks``.

    These are hand-written by the workshop author and graded by ``score_round.py``. They are the
    *gold* set: never used for training, thresholds or prompt design.
    """
    rows = []
    for path in sorted(fixtures.glob("*/*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if fixture["client_id"] not in PERSONAS:
            raise ValueError(f"{path.name}: unknown persona {fixture['client_id']}")
        rows.append({
            "id": fixture["id"],
            "persona": fixture["client_id"],
            "subject": fixture["subject"],
            "body": fixture["body"],
            "checks": canonical(fixture["expected"]["required_checks"]),
            "family": "fixture",
            "split": "gold",
            "source": "personadesk-fixture",
        })
    if not rows:
        raise FileNotFoundError(f"no fixtures under {fixtures.relative_to(ROOT.parent)}")
    return rows
