from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

from empathy_lab.baseline import fit_baseline, predict_baseline
from empathy_lab.config import ModelConfig, config_from_mapping
from empathy_lab.data import load_dataset, split_records
from empathy_lab.evaluation import evaluate

PROFILE = {
    "model_id": "Qwen/Qwen2.5-0.5B-Instruct",
    "revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    "device": "cuda",
    "dtype": "float16",
    "max_new_tokens": 160,
    "max_length": 1024,
    "batch_size": 1,
    "learning_rate": 0.0002,
    "max_steps": 10,
    "lora_rank": 8,
    "seed": 17,
    "gradient_accumulation_steps": 1,
}


def test_flat_profile_is_strict_and_uses_local_cuda_defaults() -> None:
    config = config_from_mapping(PROFILE)
    assert config.model_id == PROFILE["model_id"]
    assert config.device == "cuda"
    assert config.dtype == "float16"

    with pytest.raises(ValueError, match="unknown"):
        config_from_mapping({**PROFILE, "extra": True})
    with pytest.raises(ValueError, match="immutable"):
        config_from_mapping({**PROFILE, "revision": "main"})


def test_from_json_reads_flat_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        Path,
        "open",
        lambda self, *args, **kwargs: StringIO(json.dumps(PROFILE)),
    )
    assert ModelConfig.from_json("profile.json").revision == PROFILE["revision"]


def test_train_only_lexical_baseline_and_invalid_generation_metrics() -> None:
    splits = split_records(load_dataset())
    model = fit_baseline(splits["train"])
    predictions = predict_baseline(model, splits["test"])
    predictions[splits["test"][0]["id"]] = None

    report = evaluate(splits["test"], predictions)
    assert report.invalid_generation_rate == 1 / len(splits["test"])
    assert report.invalid_count == 1
    for metric in report.mechanisms.values():
        assert len(metric.confusion_matrix) == 3
        assert all(len(row) == 3 for row in metric.confusion_matrix)
        assert metric.valid_count == len(splits["test"]) - 1


def test_baseline_rejects_validation_data_for_fitting() -> None:
    splits = split_records(load_dataset())
    with pytest.raises(ValueError, match="train examples only"):
        fit_baseline(splits["validation"])
