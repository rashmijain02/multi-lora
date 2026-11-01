"""Locate the PersonaDesk workshop from this file's location and make it importable."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def personadesk_root() -> Path:
    configured = os.environ.get("PERSONADESK_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    # scripts/ -> agent-evals-vally/ -> workshops/
    return Path(__file__).resolve().parents[2] / "personal-agent-multilora"


def import_personadesk() -> Path:
    root = personadesk_root()
    if not (root / "hermes_plugin").is_dir():
        raise SystemExit(f"PersonaDesk workshop not found at {root.name!r}; set PERSONADESK_ROOT.")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root
