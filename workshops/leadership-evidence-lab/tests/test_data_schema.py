from __future__ import annotations

from copy import deepcopy

import pytest

from empathy_lab.data import MECHANISMS, DatasetError, load_dataset, split_records
from empathy_lab.schema import parse_model_output, target_json


def test_bundled_dataset_is_fictional_and_has_family_disjoint_splits() -> None:
    records = load_dataset()
    splits = split_records(records)

    assert len(records) == 36
    assert {name: len(items) for name, items in splits.items()} == {
        "train": 20,
        "validation": 8,
        "test": 8,
    }
    assert all(record["fictional"] is True for record in records)
    assert all(set(record["labels"]) == set(MECHANISMS) for record in records)
    families = [
        {record["scenario_family"] for record in splits[name]}
        for name in ("train", "validation", "test")
    ]
    assert not families[0] & families[1]
    assert not families[0] & families[2]
    assert not families[1] & families[2]


def test_dataset_rejects_non_verbatim_evidence() -> None:
    record = deepcopy(load_dataset()[0])
    record["labels"]["emotional_reactions"]["evidence_spans"] = ["not in the response"]

    with pytest.raises(DatasetError, match="verbatim"):
        split_records([record])


def test_dataset_rejects_cross_split_scenario_family() -> None:
    records = load_dataset()
    records[0]["scenario_family"] = records[-1]["scenario_family"]
    records[0]["split"] = "train"

    with pytest.raises(DatasetError, match="multiple splits"):
        split_records(records)


def test_training_target_matches_strict_grounded_output_schema() -> None:
    record = load_dataset()[0]
    from empathy_lab.data import as_examples

    example = as_examples([record])[0]
    parsed = parse_model_output(target_json(example), example)
    assert set(parsed) == set(MECHANISMS)


def test_model_output_rejects_extraneous_text_and_ungrounded_evidence() -> None:
    record = load_dataset()[0]
    from empathy_lab.data import as_examples

    example = as_examples([record])[0]
    valid = target_json(example)
    with pytest.raises(ValueError, match="strict JSON"):
        parse_model_output(f"Here is the result: {valid}", example)

    corrupted = valid.replace("That sounds exhausting.", "invented quote")
    with pytest.raises(ValueError, match="not found"):
        parse_model_output(corrupted, example)
