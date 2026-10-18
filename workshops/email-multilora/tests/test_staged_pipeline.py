import json
from unittest.mock import Mock

import pytest

from email_workshop import pipeline
from email_workshop.data import ADAPTERS
from email_workshop.training import TrainConfig, train_config_dict


def fake_splits():
    row = {"id": "synthetic", "subject": "Synthetic", "body": "Only test data", "labels": []}
    return {"train": [row], "validation": [row], "test": [row]}


def patch_pipeline_stages(monkeypatch):
    manifest = {
        "dataset": "synthetic-test",
        "seed": 2026,
        "splits": {name: {"rows": len(rows)} for name, rows in fake_splits().items()},
    }
    prepare = Mock(return_value=manifest)
    load_splits = Mock(return_value=(fake_splits(), manifest))
    router = Mock()
    router_metadata = {
        "target_recall": 0.95,
        "validation_domain_recall": 1.0,
    }
    fit_router = Mock(return_value=(router, router_metadata))
    train_adapter = Mock()
    training_config = train_config_dict(TrainConfig(device="cpu", max_steps=2, sample_limit=16))
    verify_adapters = Mock(
        return_value={name: {"purpose": "smoke", "config": training_config} for name in ADAPTERS}
    )
    local_backend = Mock(return_value=Mock(identity={"backend": "synthetic"}))
    lexical_predictions = Mock(return_value=[{"id": "synthetic"}])
    evaluate = Mock(return_value=[{"id": "synthetic"}])
    score = Mock(return_value=({"micro_f1": 0.5, "rows": 1}, []))
    for name, value in {
        "prepare": prepare,
        "load_splits": load_splits,
        "fit_router": fit_router,
        "train_adapter": train_adapter,
        "verify_adapters": verify_adapters,
        "LocalBackend": local_backend,
        "lexical_predictions": lexical_predictions,
        "evaluate": evaluate,
        "score": score,
    }.items():
        monkeypatch.setattr(pipeline, name, value)
    return {
        "prepare": prepare,
        "fit_router": fit_router,
        "train_adapter": train_adapter,
        "verify_adapters": verify_adapters,
        "LocalBackend": local_backend,
        "evaluate": evaluate,
    }


def test_plan_mode_has_no_stage_side_effects(tmp_path, monkeypatch, capsys):
    run_pipeline = Mock(side_effect=AssertionError("Pipeline must not run in plan mode"))
    monkeypatch.setattr(pipeline, "run_pipeline", run_pipeline)
    monkeypatch.setattr(
        "sys.argv",
        [
            "pipeline",
            "--profile",
            "smoke",
            "--artifacts",
            str(tmp_path / "run"),
        ],
    )

    pipeline.main()

    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "plan only; no downloads, training, evaluation, or cloud calls"
    assert result["stages"] == list(pipeline.STAGES)
    assert result["config"]["device"] == "cpu"
    assert result["config"]["max_steps"] == 2
    assert result["config"]["sample_limit"] == 16
    assert result["config"]["evaluation_limit"] == 4
    run_pipeline.assert_not_called()


def test_full_plan_uses_separate_default_root(monkeypatch):
    monkeypatch.setattr("sys.argv", ["pipeline", "--profile", "full"])
    args = pipeline.build_parser().parse_args()

    config = pipeline.resolved_config(args)

    assert config.root.name == "pipeline-full"
    assert config.device == "cuda"
    assert config.max_steps == -1
    assert config.sample_limit is None
    assert config.evaluation_limit is None


def test_model_override_is_preserved_in_plan(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "pipeline",
            "--profile",
            "smoke",
            "--model-profile",
            "custom",
            "--model-id",
            "nvidia/example",
            "--model-revision",
            "immutable-revision",
            "--target-modules",
            "q_proj",
            "v_proj",
        ],
    )

    config = pipeline.resolved_config(pipeline.build_parser().parse_args())

    assert config.model_profile == "custom"
    assert config.model_id == "nvidia/example"
    assert config.model_revision == "immutable-revision"
    assert config.target_modules == ("q_proj", "v_proj")


def test_smoke_pipeline_runs_all_stages_and_writes_result(tmp_path, monkeypatch):
    calls = patch_pipeline_stages(monkeypatch)
    config = pipeline.PipelineConfig(
        root=tmp_path / "run",
        profile="smoke",
        device="cpu",
        max_steps=2,
        sample_limit=16,
        evaluation_limit=4,
    )

    result = pipeline.run_pipeline(config)

    assert result["status"] == "completed"
    assert list(result["stages"]) == list(pipeline.STAGES)
    calls["prepare"].assert_called_once_with(config.root, 2026, None)
    calls["fit_router"].assert_called_once_with(config.root, 0.95)
    assert [call.args[1] for call in calls["train_adapter"].call_args_list] == list(ADAPTERS)
    assert all(
        call.args[2].model_id == config.model_id
        and call.args[2].model_revision == config.model_revision
        for call in calls["train_adapter"].call_args_list
    )
    assert calls["evaluate"].call_count == 4
    assert {call.args[4] for call in calls["evaluate"].call_args_list} == set(pipeline.STRATEGIES)
    assert (config.root / "pipeline" / "status.json").is_file()
    saved = json.loads((config.root / "pipeline" / "result.json").read_text(encoding="utf-8"))
    assert saved["status"] == "completed"


def test_pipeline_reuses_verified_data_and_adapters(tmp_path, monkeypatch):
    calls = patch_pipeline_stages(monkeypatch)
    root = tmp_path / "run"
    (root / "data").mkdir(parents=True)
    (root / "data" / "manifest.json").write_text("{}", encoding="utf-8")
    for adapter in ADAPTERS:
        directory = root / "adapters" / adapter
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
    config = pipeline.PipelineConfig(
        root=root,
        profile="smoke",
        device="cpu",
        max_steps=2,
        sample_limit=16,
        evaluation_limit=4,
    )

    result = pipeline.run_pipeline(config)

    calls["prepare"].assert_not_called()
    calls["train_adapter"].assert_not_called()
    assert result["stages"]["prepare"]["reused"] is True
    assert result["stages"]["train"]["reused"] is True
    assert result["stages"]["train"]["reusedAdapters"] == list(ADAPTERS)


def test_partial_adapter_directory_is_rejected(tmp_path, monkeypatch):
    calls = patch_pipeline_stages(monkeypatch)
    root = tmp_path / "run"
    (root / "adapters" / "generalist").mkdir(parents=True)
    config = pipeline.PipelineConfig(
        root=root,
        profile="smoke",
        device="cpu",
        max_steps=2,
        sample_limit=16,
        evaluation_limit=4,
    )

    with pytest.raises(RuntimeError, match="Incomplete adapter directory"):
        pipeline.run_pipeline(config)

    calls["verify_adapters"].assert_not_called()


def test_full_profile_rejects_smoke_limits(tmp_path):
    with pytest.raises(ValueError, match="full profile cannot use smoke limits"):
        pipeline.PipelineConfig(
            root=tmp_path,
            profile="full",
            device="cuda",
            max_steps=2,
        )
