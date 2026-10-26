import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WORKSHOP = Path(__file__).resolve().parents[1]
SCRIPTS = WORKSHOP / "scripts"
pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX shell required")


def run_script(name, arguments, cwd, environment=None):
    return subprocess.run(
        ["sh", os.path.relpath(SCRIPTS / name, cwd), *map(str, arguments)],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def capture_executable(path):
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def dataset_at(path):
    path.mkdir()
    for split in ("train", "valid"):
        (path / f"{split}.jsonl").write_text('{"text":"test fixture"}\n', encoding="utf-8")
    return path


def test_training_requires_dataset_and_new_output(tmp_path):
    result = run_script("train-nemotron.sh", [], tmp_path)
    assert result.returncode == 2
    assert "Usage:" in result.stderr
    result = run_script("train-nemotron.sh", ["missing-dataset", "unused-output"], tmp_path)
    assert result.returncode == 2
    assert "Missing or empty dataset split" in result.stderr


def test_training_rejects_existing_output(tmp_path):
    dataset = dataset_at(tmp_path / "dataset")
    output = tmp_path / "existing-output"
    output.mkdir()
    result = run_script("train-nemotron.sh", [dataset, output], tmp_path)
    assert result.returncode == 2
    assert "already exists" in result.stderr


def test_training_uses_workshop_config_from_another_directory(tmp_path):
    dataset = dataset_at(tmp_path / "dataset")
    output = tmp_path / "new-output"
    python_bin = capture_executable(tmp_path / "fake-python")
    environment = {**os.environ, "MLX_PYTHON": str(python_bin)}
    result = run_script(
        "train-nemotron.sh", [dataset, output, "--iters", "2"], tmp_path, environment
    )
    assert result.returncode == 0, result.stderr
    captured = json.loads(result.stdout)
    assert Path(captured["cwd"]) == WORKSHOP
    assert captured["args"] == [
        "-m", "mlx_lm", "lora", "--config", "config/nemotron_mlx_lora.yaml",
        "--train", "--data", str(dataset), "--adapter-path", str(output), "--iters", "2",
    ]
    assert (WORKSHOP / "config" / "nemotron_mlx_lora.yaml").is_file()
    assert not output.exists()


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
def test_serving_preserves_localhost_default_and_opt_in_lan(tmp_path, host):
    capture_executable(tmp_path / "vllm")
    environment = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"}
    for name in ("NEMOTRON_HOST", "NEMOTRON_PORT", "NEMOTRON_MODEL"):
        environment.pop(name, None)
    if host == "0.0.0.0":
        environment["NEMOTRON_HOST"] = host
    result = run_script("serve-nemotron.sh", [], tmp_path, environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads(result.stdout)["args"]
    assert arguments[:2] == ["serve", "nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16"]
    assert arguments[arguments.index("--host") + 1] == host
    assert arguments[arguments.index("--served-model-name") + 1] == "nemotron-local"