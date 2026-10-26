"""Locate the workshop checkout and runtime folders without embedding machine paths."""

from __future__ import annotations

import os
from pathlib import Path

PERMISSIONS_RELATIVE = Path("config") / "persona_permissions.json"


def workshop_root(configured: str | None = None) -> Path:
    """Return the workshop directory that contains ``config/persona_permissions.json``.

    Resolution order: explicit setting, ``PERSONADESK_ROOT``, then the directory above this
    package (works when the installed plugin folder is a symlink into the checkout).
    """
    for value in (configured, os.environ.get("PERSONADESK_ROOT")):
        if value:
            root = Path(value).expanduser().resolve()
            if not (root / PERMISSIONS_RELATIVE).is_file():
                raise FileNotFoundError(f"{PERMISSIONS_RELATIVE} not found under configured root")
            return root
    root = Path(__file__).resolve().parents[1]
    if (root / PERMISSIONS_RELATIVE).is_file():
        return root
    raise FileNotFoundError(
        "Cannot locate the PersonaDesk workshop. Set PERSONADESK_ROOT or the plugin setting "
        "'workshop_root'."
    )


def artifacts_dir(root: Path) -> Path:
    path = root / "artifacts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def email_workshop_root(root: Path) -> Path:
    return root.parent / "email-multilora"


def safe_child(base: Path, *parts: str) -> Path:
    """Join parts under ``base`` and refuse anything that escapes it."""
    resolved_base = base.resolve()
    path = resolved_base.joinpath(*parts).resolve()
    if path != resolved_base and resolved_base not in path.parents:
        raise ValueError("Path escapes its allowed directory.")
    return path
