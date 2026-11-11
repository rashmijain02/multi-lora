from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from empathy_lab import corpora
from empathy_lab.config import ModelConfig, config_from_mapping
from empathy_lab.corpora import (
    ExperimentConfig,
    deduplicate_splits,
    dialogue_records,
    load_experiment,
    load_prepared,
    prepare,
)
from empathy_lab.experiment import baseline
from empathy_lab.tasks import (
    emotion_record,
    parse_prediction,
    task_metrics,
    validate_records,
)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ExperimentConfig:
    monkeypatch.setattr(corpora, "WORKSHOP_ROOT", tmp_path)
    return ExperimentConfig(
        "unit-run",
        "go_emotions",
        ModelConfig("unit/model", "a" * 40, device="cpu", dtype="float32"),
        {"revision": "b" * 40},
        {"train": 2, "validation": 1, "test": 1},
        42,
    )


@pytest.fixture
def records() -> list:
    return [
        emotion_record(f"{split}-{index}", split, f"invented {split} text {index}", [27])
        for split in ("train", "validation", "test")
        for index in range(3)
    ]


def test_experiment_config_reuses_profile_and_validates_overrides(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    profile = root / "configs" / "experiments" / "goemotions-local.json"
    loaded = load_experiment(profile)
    assert loaded.model.gradient_checkpointing
    assert loaded.model.max_steps == 20
    assert loaded.limits["train"] == 64
    assert loaded.model.revision != loaded.dataset["revision"]

    raw = json.loads((root / "configs" / "qwen-local.json").read_text())
    extended = config_from_mapping(
        {
            **raw,
            "lora_target_modules": ["q_proj", "v_proj"],
            "lora_alpha": 32,
            "eval_steps": 2,
            "chat_template_kwargs": {"enable_thinking": False},
        }
    )
    assert extended.lora_target_modules == ("q_proj", "v_proj")
    for overrides in (
        {"learning_rate": float("nan")},
        {"gradient_checkpointing": "true"},
        {"chat_template_kwargs": {"enable_thinking": "false"}},
        {"lora_target_modules": []},
        {"device": "cuda:invalid"},
    ):
        with pytest.raises(ValueError):
            config_from_mapping({**raw, **overrides})


def test_dialogue_targets_are_listener_turns_without_future_context() -> None:
    rows = [
        {"conv_id": "fictional-dialogue", "utterance_idx": str(index), "utterance": text}
        for index, text in enumerate(
            ["invented opening", "invented response", "invented followup", "invented conclusion"], 1
        )
    ]
    items = dialogue_records(rows, "train")
    assert [item.target for item in items] == ["invented response", "invented conclusion"]
    assert [message["role"] for message in items[1].messages] == ["user", "assistant", "user"]
    assert all(message["content"] != items[0].target for message in items[0].messages)
    assert all(item.group == "fictional-dialogue" for item in items)
    with pytest.raises(ValueError, match="contiguous"):
        dialogue_records([rows[0], rows[2]], "train")
    audit = {}
    assert dialogue_records([rows[0], rows[2]], "train", audit=audit) == []
    assert audit["incomplete_conversations_dropped"] == 1
    assert audit["incomplete_utterances_dropped"] == 2


def test_data_validation_rejects_cross_split_groups_and_unknown_labels(records: list) -> None:
    assert validate_records(records, "go_emotions")["train"] == 3
    corrupted = [*records[:-1], replace(records[-1], group=records[0].group)]
    with pytest.raises(ValueError, match="multiple splits"):
        validate_records(corrupted, "go_emotions")
    for raw in (
        '{"labels":["invented"]}',
        '{"labels":[]}',
        '{"labels":["neutral","neutral"]}',
        '{"labels":["neutral"],"labels":["joy"]}',
        '{"labels":["neutral"],"score":2}',
    ):
        with pytest.raises(ValueError):
            parse_prediction("go_emotions", raw, records[0])
    with pytest.raises(ValueError):
        emotion_record("id", "train", "invented", [True])


def test_cross_split_input_deduplication_is_explicit(records: list) -> None:
    duplicated = replace(records[3], messages=records[0].messages)
    retained, dropped = deduplicate_splits([*records[:3], duplicated, *records[4:]])
    assert dropped == {"train": 0, "validation": 1, "test": 0}
    assert duplicated not in retained


def test_preparation_is_reproducible_and_detects_tampering(
    config: ExperimentConfig, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(corpora, "_read_sources", lambda *args: (records, {"license": "unit"}))
    first = prepare(config)
    second = prepare(config)
    assert first["data_fingerprint"] == second["data_fingerprint"]
    assert first["selected_counts"] == {"train": 2, "validation": 1, "test": 1}
    loaded, _ = load_prepared(config)
    assert len(loaded) == 4
    path = config.prepared_dir / "train.jsonl"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        load_prepared(config)


def test_training_split_loader_never_opens_test_data(
    config: ExperimentConfig, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(corpora, "_read_sources", lambda *args: (records, {}))
    prepare(config)
    (config.prepared_dir / "test.jsonl").unlink()
    selected, _ = load_prepared(config, ("train", "validation"))
    assert {item.split for item in selected} == {"train", "validation"}


def test_invalid_emotion_outputs_are_not_rewarded(records: list) -> None:
    evaluation = [item for item in records if item.split == "validation"][:2]
    metrics = task_metrics("go_emotions", evaluation, [[27], None])
    assert metrics["coverage"] == 0.5
    assert metrics["all_example_exact_match"] == 0.5
    assert metrics["micro_f1"] == pytest.approx(2 / 3)
    with pytest.raises(ValueError, match="training"):
        task_metrics("go_emotions", records[:1], [[27]])


def test_baseline_handles_single_class_labels_and_reports_no_text(
    config: ExperimentConfig, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(corpora, "_read_sources", lambda *args: (records, {}))
    prepare(config)
    report = baseline(config, "validation")
    assert report["metrics"]["all_example_exact_match"] == 1
    assert "invented" not in json.dumps(report)
    with pytest.raises(FileExistsError):
        baseline(config, "validation")


def test_public_data_never_enters_fictional_loader() -> None:
    from empathy_lab.data import as_examples

    with pytest.raises(ValueError):
        as_examples([emotion_record("id", "train", "invented", [27]).to_dict()])


def test_source_group_validation_precedes_subset_selection(
    config: ExperimentConfig, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    corrupted = [*records[:-1], replace(records[-1], group=records[0].group)]
    monkeypatch.setattr(corpora, "_read_sources", lambda *args: (corrupted, {}))
    with pytest.raises(ValueError, match="multiple splits"):
        prepare(config)


def test_dialogue_archive_checksum_is_verified_before_parsing(
    config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(config, task="empathetic_dialogues", dataset={"revision": "c" * 64})
    folder = corpora.WORKSHOP_ROOT / "data" / "external" / "empathetic_dialogues"
    folder.mkdir(parents=True)
    (folder / "empatheticdialogues.tar.gz").write_bytes(b"not a dataset archive")
    monkeypatch.setattr(
        corpora.tarfile,
        "open",
        lambda *args, **kwargs: pytest.fail("unverified archive must never be parsed"),
    )
    with pytest.raises(ValueError, match="checksum"):
        corpora._read_sources(config, False)


def test_adapter_provenance_mismatch_precedes_model_loading(
    config: ExperimentConfig, records: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import asdict

    from empathy_lab import inference
    from empathy_lab.experiment import evaluate

    monkeypatch.setattr(corpora, "_read_sources", lambda *args: (records, {}))
    manifest = prepare(config)
    directory = config.run_dir()
    directory.mkdir(parents=True)
    (directory / "training.json").write_text(
        json.dumps(
            {
                "task": config.task,
                "model": {**asdict(config.model), "revision": "d" * 40},
                "data_fingerprint": manifest["data_fingerprint"],
            }
        )
    )
    monkeypatch.setattr(
        inference,
        "load_hf_model",
        lambda *args, **kwargs: pytest.fail("mismatched adapter must not be loaded"),
    )
    with pytest.raises(ValueError, match="provenance"):
        evaluate(config, "validation", adapted=True)


def test_cli_dispatches_public_tasks_without_the_fictional_loader(
    config: ExperimentConfig,
    records: list,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from empathy_lab import __main__, experiment

    monkeypatch.setattr(corpora, "_read_sources", lambda *args: (records, {}))
    prepare(config)
    monkeypatch.setattr(experiment, "load_experiment", lambda *args: config)
    monkeypatch.setattr(
        __main__,
        "load_dataset",
        lambda *args: pytest.fail("public tasks must not pass through the fictional loader"),
    )
    assert __main__.main(["experiment", "validate", "--config", "unit.json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["task"] == "go_emotions"
    assert report["selected_counts"]["train"] == 2


def test_missing_shards_cannot_silently_become_a_smaller_dataset() -> None:
    files = [Path(f"train-{index:05d}-of-00002.parquet") for index in range(2)]
    corpora.validate_shards(files, "train")
    with pytest.raises(ValueError, match="incomplete"):
        corpora.validate_shards(files[:1], "train")


def test_emotion_label_order_is_checked_against_parquet_metadata(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from empathy_lab.tasks import EMOTIONS

    path = tmp_path / "synthetic.parquet"
    table = pa.table({"text": ["invented example"], "labels": [[0]]})
    for names in (list(reversed(EMOTIONS)), list(EMOTIONS)):
        metadata = {"info": {"features": {"labels": {"feature": {"names": names}}}}}
        pq.write_table(
            table.replace_schema_metadata({b"huggingface": json.dumps(metadata).encode()}),
            path,
        )
        if names == list(EMOTIONS):
            corpora.validate_emotion_schema(path)
        else:
            with pytest.raises(ValueError, match="label-index"):
                corpora.validate_emotion_schema(path)
