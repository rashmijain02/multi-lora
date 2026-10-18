import ast
import json
import os
import re
from pathlib import Path, PurePosixPath
from unittest.mock import Mock

import pytest

from email_workshop import serving

WORKSHOP = Path(__file__).resolve().parents[1]
REPOSITORY = WORKSHOP.parents[1]


def test_no_machine_specific_checkout_paths():
    pattern = re.compile(r"(?<!\w)[A-Za-z]:[\\/](?!/)|/(?:mnt|home|Users)/")
    suffixes = {".md", ".mdc", ".py", ".ps1", ".sh", ".json", ".ipynb", ".code-workspace"}
    excluded = {
        ".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
        ".ipynb_checkpoints", ".copilot-azure", "artifacts", ".cache",
    }
    for directory, names, files in os.walk(REPOSITORY):
        names[:] = [name for name in names if name not in excluded]
        for name in files:
            path = Path(directory) / name
            if path.suffix not in suffixes:
                continue
            text = path.read_text(encoding="utf-8")
            assert not pattern.search(text), str(path.relative_to(REPOSITORY))


def test_notebook_artifacts_are_workshop_relative(monkeypatch):
    monkeypatch.setenv("EMAIL_WORKSHOP_RUN", "artifacts/custom-run")
    for path in (WORKSHOP / "notebooks").glob("*.ipynb"):
        notebook = json.loads(path.read_text(encoding="utf-8"))
        config = next(cell for cell in notebook["cells"] if cell.get("id") == "config")
        source = config["source"]
        tree = ast.parse("".join(source) if isinstance(source, list) else source)
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "ARTIFACT_DIR"
                    for target in node.targets)
        )
        value = eval(compile(ast.Expression(assignment.value), "<artifact-config>", "eval"), {
            "Path": Path, "os": os, "WORKSHOP_ROOT": WORKSHOP,
        })
        assert value == WORKSHOP / "artifacts" / "custom-run"


def test_vllm_command_uses_relative_adapter_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(serving, "verify_adapters", Mock(return_value={
        "generalist": {"config": {
            "model_id": "test-model", "model_revision": "test-revision",
            "rank": 8, "max_length": 512,
        }},
    }))
    command = serving.vllm_command(tmp_path, "artifacts/test")
    modules = command[command.index("--lora-modules") + 1:]
    assert modules == [f"{name}=artifacts/test/adapters/{name}" for name in serving.ADAPTERS]
    assert all(not PurePosixPath(item.split("=", 1)[1]).is_absolute() for item in modules)


@pytest.mark.parametrize("path", ["", "../outside", "artifacts/../../outside", "artifacts\\test"])
def test_vllm_rejects_nonportable_paths(monkeypatch, tmp_path, path):
    monkeypatch.setattr(serving, "verify_adapters", Mock(return_value={
        "generalist": {"config": {}},
    }))
    with pytest.raises(ValueError, match="relative POSIX"):
        serving.vllm_command(tmp_path, path)


def test_vllm_rejects_absolute_runtime_path(monkeypatch, tmp_path):
    monkeypatch.setattr(serving, "verify_adapters", Mock(return_value={
        "generalist": {"config": {}},
    }))
    with pytest.raises(ValueError, match="relative POSIX"):
        serving.vllm_command(tmp_path, tmp_path.as_posix())
