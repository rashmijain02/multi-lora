"""Mechanism-wise evaluation with explicit invalid-generation accounting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .data import as_examples
from .dataset import MECHANISMS, Example

LABELS = (0, 1, 2)


@dataclass(frozen=True)
class MechanismMetrics:
    macro_f1: float | None
    balanced_accuracy: float | None
    confusion_matrix: list[list[int]]
    valid_count: int
    invalid_count: int


@dataclass(frozen=True)
class EvaluationReport:
    example_count: int
    invalid_count: int
    invalid_generation_rate: float
    mechanisms: dict[str, MechanismMetrics]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validated_scores(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping) or set(value) != set(MECHANISMS):
        return None
    if any(type(value[key]) is not int or value[key] not in LABELS for key in MECHANISMS):
        return None
    return {key: value[key] for key in MECHANISMS}


def evaluate_predictions(
    examples: Sequence[Example | dict[str, Any]], predictions: Mapping[str, Any]
) -> EvaluationReport:
    """Compute fixed-label metrics; missing/malformed predictions remain invalid."""
    examples = as_examples(examples)
    if any(example.split == "train" for example in examples):
        raise ValueError("evaluation accepts validation or test examples, never train examples")
    ids = [example.id for example in examples]
    if len(set(ids)) != len(ids):
        raise ValueError("evaluation examples must have unique IDs")

    valid_predictions = {
        example.id: _validated_scores(predictions.get(example.id)) for example in examples
    }
    invalid_ids = {example_id for example_id, scores in valid_predictions.items() if scores is None}
    results: dict[str, MechanismMetrics] = {}
    for mechanism in MECHANISMS:
        matrix = [[0 for _ in LABELS] for _ in LABELS]
        support = [0 for _ in LABELS]
        true_positive = [0 for _ in LABELS]
        predicted_count = [0 for _ in LABELS]
        valid_count = 0
        for example in examples:
            scores = valid_predictions[example.id]
            if scores is None:
                continue
            actual = example.labels[mechanism].score
            predicted = scores[mechanism]
            matrix[actual][predicted] += 1
            support[actual] += 1
            predicted_count[predicted] += 1
            if actual == predicted:
                true_positive[actual] += 1
            valid_count += 1

        if valid_count:
            f1s = []
            recalls = []
            for index in range(len(LABELS)):
                precision = (
                    true_positive[index] / predicted_count[index] if predicted_count[index] else 0.0
                )
                recall = true_positive[index] / support[index] if support[index] else 0.0
                f1s.append(
                    2 * precision * recall / (precision + recall) if precision + recall else 0.0
                )
                recalls.append(recall)
            macro_f1: float | None = sum(f1s) / len(LABELS)
            balanced_accuracy: float | None = sum(recalls) / len(LABELS)
        else:
            macro_f1 = None
            balanced_accuracy = None
        results[mechanism] = MechanismMetrics(
            macro_f1=macro_f1,
            balanced_accuracy=balanced_accuracy,
            confusion_matrix=matrix,
            valid_count=valid_count,
            invalid_count=len(examples) - valid_count,
        )

    total = len(examples)
    return EvaluationReport(
        example_count=total,
        invalid_count=len(invalid_ids),
        invalid_generation_rate=(len(invalid_ids) / total if total else 0.0),
        mechanisms=results,
    )


def evaluate(
    records: Sequence[Example | dict[str, Any]], predictions: Mapping[str, Any]
) -> EvaluationReport:
    """Notebook-facing evaluation API."""
    return evaluate_predictions(records, predictions)
