"""Notebook-facing dictionary API for the fictional workshop dataset."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .dataset import (
    DEFAULT_DATA_PATH,
    MECHANISMS,
    SPLITS,
    DatasetError,
    Example,
    _parse_example,
)
from .dataset import (
    load_dataset as _load_examples,
)
from .dataset import (
    validate_examples as _validate_examples,
)


def _record_from_example(example: Example) -> dict[str, Any]:
    return {
        "id": example.id,
        "fictional": True,
        "scenario_family": example.scenario_family,
        "split": example.split,
        "conversation": [
            {"role": turn.role, "content": turn.content} for turn in example.conversation
        ],
        "labels": {
            mechanism: {
                "score": example.labels[mechanism].score,
                "rationale": example.labels[mechanism].rationale,
                "evidence_spans": list(example.labels[mechanism].evidence_spans),
            }
            for mechanism in MECHANISMS
        },
    }


def _example_from_record(record: Example | dict[str, Any], index: int = 1) -> Example:
    if isinstance(record, Example):
        return record
    return _parse_example(record, index)


def as_examples(
    records: Iterable[Example | dict[str, Any]], *, require_all_splits: bool = False
) -> list[Example]:
    """Validate public dictionary records and convert them to the internal representation."""
    examples = [_example_from_record(record, index) for index, record in enumerate(records, 1)]
    return _validate_examples(examples, require_all_splits=require_all_splits) if examples else []


def load_dataset(path: str | Path = DEFAULT_DATA_PATH) -> list[dict[str, Any]]:
    """Load the bundled fictional JSONL data as validated, mutable dictionary records."""
    return [_record_from_example(example) for example in _load_examples(path)]


def split_records(
    records: Iterable[Example | dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return records grouped by their preassigned, scenario-disjoint split."""
    examples = as_examples(records, require_all_splits=True)
    return {
        split: [_record_from_example(example) for example in examples if example.split == split]
        for split in SPLITS
    }


__all__ = ["MECHANISMS", "DatasetError", "load_dataset", "split_records"]
