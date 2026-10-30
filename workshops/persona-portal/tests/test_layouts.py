"""Phase 1 gate: every persona layout is valid against the panel catalogue."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

UX = Path(__file__).resolve().parent.parent / "ux"
PERMISSIONS = (
    Path(__file__).resolve().parents[2] / "personal-agent-multilora" / "config" / "persona_permissions.json"
)
CATALOG = json.loads((UX / "catalog.json").read_text(encoding="utf-8"))
PERSONAS = json.loads(PERMISSIONS.read_text(encoding="utf-8"))["personas"]
LAYOUTS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in UX.glob("*.json") if p.name != "catalog.json"}
REQUIRED_KEYS = {"persona", "display_name", "role", "hermes_profile", "release", "panels",
                 "default_panel", "style", "intent"}


def test_one_layout_per_persona():
    assert set(LAYOUTS) == set(PERSONAS)


def test_mvp_layouts_are_the_enabled_personas():
    mvp = {pid for pid, layout in LAYOUTS.items() if layout["release"] == "mvp"}
    enabled = {pid for pid, cfg in PERSONAS.items() if cfg["enabled"]}
    assert mvp == enabled == {"priya-raman-support", "daniel-okafor-cfo", "noah-williams-assistant"}


@pytest.mark.parametrize("persona", sorted(LAYOUTS))
def test_layout_is_valid(persona):
    layout = LAYOUTS[persona]
    assert set(layout) == REQUIRED_KEYS
    assert layout["persona"] == persona
    assert layout["hermes_profile"] == PERSONAS[persona]["hermes_profile"]
    assert layout["release"] in {"mvp", "planned"}
    panels = layout["panels"]
    assert panels and len(panels) == len(set(panels))
    assert set(panels) <= set(CATALOG["panels"]), "layout uses a panel outside the catalogue"
    assert {"work-queue", "draft-review", "spend"} <= set(panels), "catalogue says these are for all"
    assert layout["default_panel"] == panels[0]
    style = layout["style"]
    assert re.fullmatch(r"#[0-9a-f]{6}", style["accent"])
    for key in ("density", "font", "contrast"):
        assert style[key] in CATALOG["style"][key]


def test_available_panels_have_routes_and_planned_ones_have_phases():
    for panel_id, spec in CATALOG["panels"].items():
        if spec["status"] == "available":
            assert spec["route"].startswith("/v1/"), panel_id
        else:
            assert spec["status"] == "planned" and isinstance(spec["phase"], int), panel_id


@pytest.mark.parametrize("path", sorted(UX.glob("*.json")), ids=lambda p: p.name)
def test_no_secrets_or_machine_paths(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:\\|/Users/|/home/|\\\\", text), "absolute path in layout"
    assert not re.search(r"(?i)token|api[_-]?key|secret|password", text)
