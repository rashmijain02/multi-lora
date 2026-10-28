from __future__ import annotations

import getpass
import json
import shutil
import sys
from pathlib import Path

import pytest

WORKSHOP = Path(__file__).resolve().parents[1]
REPO = WORKSHOP.parents[1]
CLM_SRC = REPO / "external" / "CLM" / "src"
if CLM_SRC.is_dir() and str(CLM_SRC) not in sys.path:
    sys.path.append(str(CLM_SRC))

from hermes_plugin.store import open_store
from hermes_plugin.tools import Runtime, make_handlers

FAKE_HERMES = str(WORKSHOP / "scripts" / "fake_hermes.py")


@pytest.fixture
def root(tmp_path, monkeypatch) -> Path:
    """An isolated copy of the workshop data with the current OS user as operator."""
    copy = tmp_path / "pd"
    for name in ("config", "fixtures", "policies", "hermes_plugin", "scripts"):
        shutil.copytree(WORKSHOP / name, copy / name,
                        ignore=shutil.ignore_patterns("__pycache__", "operators.json"))
    (copy / "config" / "operators.json").write_text(json.dumps({
        "operators": {getpass.getuser(): ["priya-raman-support", "daniel-okafor-cfo",
                                          "noah-williams-assistant"]}
    }), encoding="utf-8")
    monkeypatch.setenv("PERSONADESK_ROOT", str(copy))
    monkeypatch.delenv("FAKE_HERMES_MODE", raising=False)
    return copy


@pytest.fixture
def db(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "state.db"
    monkeypatch.setenv("PERSONADESK_STATE_DB", str(path))
    return path


def runtime(root: Path, db: Path, profile: str | None, **settings) -> Runtime:
    return Runtime(root=root, settings={"writer_backend": "template", **settings},
                   profile_name=lambda: profile, store_factory=lambda: open_store(db))


def call(rt: Runtime, tool: str, **args) -> dict:
    return json.loads(make_handlers(rt)[tool](args))
