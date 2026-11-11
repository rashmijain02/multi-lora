"""Task-specific prompts, output contracts, and metrics; no dataset downloads."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .dataset import MECHANISMS, SPLITS, Example
from .schema import (
    _object_without_duplicate_keys,
    build_prompt,
    parse_evidence_output,
    scores_from_output,
    target_json,
)

EMOTIONS = (
    "admiration",
    "amusement",
    "anger",
    "annoyance",
    "approval",
    "caring",
    "confusion",
    "curiosity",
    "desire",
    "disappointment",
    "disapproval",
    "disgust",
    "embarrassment",
    "excitement",
    "fear",
    "gratitude",
    "grief",
    "joy",
    "love",
    "nervousness",
    "optimism",
    "pride",
    "realization",
    "relief",
    "remorse",
    "sadness",
    "surprise",
    "neutral",
)
TASKS = ("fictional_empathy", "go_emotions", "empathetic_dialogues")


@dataclass(frozen=True)
class TaskRecord:
    id: str
    group: str
    split: str
    messages: list[dict[str, str]]
    target: str
    evidence_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fictional_record(example: Example) -> TaskRecord:
    return TaskRecord(
        example.id,
        example.scenario_family,
        example.split,
        [{"role": "user", "content": build_prompt(example)}],
        target_json(example),
        "\n".join(turn.content for turn in example.conversation if turn.role == "assistant"),
    )


def emotion_record(identifier: str, split: str, text: str, labels: Sequence[int]) -> TaskRecord:
    if (
        not labels
        or any(type(label) is not int or not 0 <= label < len(EMOTIONS) for label in labels)
        or len(set(labels)) != len(labels)
    ):
        raise ValueError("GoEmotions labels must be unique integer indices in the 28-label schema")
    prompt = (
        "Classify the emotions expressed in this comment. Emotions are not empathy scores. "
        'Return only {"labels":["label",...]} using one or more labels from: '
        + ", ".join(EMOTIONS)
        + ".\nComment:\n"
        + text
    )
    return TaskRecord(
        identifier,
        identifier,
        split,
        [{"role": "user", "content": prompt}],
        json.dumps({"labels": [EMOTIONS[label] for label in sorted(labels)]}),
    )


def parse_prediction(task: str, raw: str, record: TaskRecord) -> Any:
    if task == "fictional_empathy":
        return scores_from_output(parse_evidence_output(raw, record.evidence_text or ""))
    if task == "go_emotions":
        value = json.loads(raw, object_pairs_hook=_object_without_duplicate_keys)
        if not isinstance(value, dict) or set(value) != {"labels"}:
            raise ValueError("emotion output must contain only labels")
        labels = value["labels"]
        if (
            not isinstance(labels, list)
            or not labels
            or any(not isinstance(label, str) or label not in EMOTIONS for label in labels)
            or len(set(labels)) != len(labels)
        ):
            raise ValueError("emotion labels must be a non-empty, unique list of known labels")
        return [EMOTIONS.index(label) for label in labels]
    if task == "empathetic_dialogues":
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("generated response must be non-empty")
        return raw.strip()
    raise ValueError(f"unknown task: {task}")


def validate_records(
    records: Sequence[TaskRecord], task: str, *, require_all_splits: bool = True
) -> dict[str, int]:
    if task not in TASKS:
        raise ValueError("unknown task")
    identifiers: set[str] = set()
    groups: dict[str, str] = {}
    counts = dict.fromkeys(SPLITS, 0)
    for record in records:
        if not record.id or not record.group or record.id in identifiers:
            raise ValueError("record IDs must be unique and IDs/groups must be non-empty")
        identifiers.add(record.id)
        if record.split not in SPLITS:
            raise ValueError("record has unknown split")
        previous = groups.setdefault(record.group, record.split)
        if previous != record.split:
            raise ValueError("a conversation/scenario group occurs in multiple splits")
        if not isinstance(record.messages, list) or not record.messages:
            raise ValueError("record messages must be non-empty")
        expected = "user"
        for index, message in enumerate(record.messages):
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or not isinstance(message["content"], str)
                or not message["content"].strip()
            ):
                raise ValueError("messages require role and non-empty content")
            if index == 0 and message["role"] == "system":
                continue
            if message["role"] != expected:
                raise ValueError("conversation roles must alternate and end with user")
            expected = "assistant" if expected == "user" else "user"
        if record.messages[-1]["role"] != "user":
            raise ValueError("conversation must end with user before the target response")
        if task != "fictional_empathy" and record.evidence_text is not None:
            raise ValueError("public tasks must not carry fictional empathy evidence")
        parse_prediction(task, record.target, record)
        counts[record.split] += 1
    if not records or (require_all_splits and not all(counts.values())):
        raise ValueError("non-empty train, validation, and test splits are required")
    return counts


def render_messages(record: TaskRecord, tokenizer: Any, model_id: str, options: dict) -> str:
    messages = list(record.messages)
    if "nemotron" in model_id.lower() and not options:
        messages = [{"role": "system", "content": "detailed thinking off"}, *messages]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, **options
    )


def task_metrics(
    task: str, records: Sequence[TaskRecord], predictions: Sequence[Any | None]
) -> dict[str, Any]:
    """Invalid classification generations count as failures in all-example metrics."""
    from sklearn.metrics import accuracy_score, f1_score
    from sklearn.preprocessing import MultiLabelBinarizer

    if not records or len(records) != len(predictions):
        raise ValueError("non-empty records and one prediction per record are required")
    if any(record.split == "train" for record in records):
        raise ValueError("evaluation does not accept training records")
    valid = [index for index, value in enumerate(predictions) if value is not None]
    result: dict[str, Any] = {
        "examples": len(records),
        "valid": len(valid),
        "invalid": len(records) - len(valid),
        "coverage": len(valid) / len(records),
    }
    gold = [parse_prediction(task, record.target, record) for record in records]
    if task == "fictional_empathy":
        result["mechanisms"] = {
            mechanism: {
                "valid_only_macro_f1": (
                    f1_score(
                        [gold[i][mechanism] for i in valid],
                        [predictions[i][mechanism] for i in valid],
                        labels=[0, 1, 2],
                        average="macro",
                        zero_division=0,
                    )
                    if valid
                    else None
                ),
                "all_example_correct_rate": sum(
                    predictions[i][mechanism] == gold[i][mechanism] for i in valid
                )
                / len(records),
            }
            for mechanism in MECHANISMS
        }
    elif task == "go_emotions":
        encoder = MultiLabelBinarizer(classes=list(range(len(EMOTIONS))))
        actual = encoder.fit_transform(gold)
        predicted = encoder.transform([value or [] for value in predictions])
        result.update(
            micro_f1=f1_score(actual, predicted, average="micro", zero_division=0),
            macro_f1=f1_score(actual, predicted, average="macro", zero_division=0),
            all_example_exact_match=accuracy_score(actual, predicted),
            metric_labels=list(EMOTIONS),
            invalid_policy="invalid generations predict an empty label set",
        )
    else:
        scores = []
        exact = 0
        for reference, prediction in zip(gold, predictions, strict=True):
            reference_tokens = re.findall(r"\w+", reference.lower())
            tokens = re.findall(r"\w+", (prediction or "").lower())
            overlap = sum((Counter(reference_tokens) & Counter(tokens)).values())
            scores.append(
                2 * overlap / (len(tokens) + len(reference_tokens))
                if tokens and reference_tokens
                else 0.0
            )
            exact += bool(prediction is not None and prediction == reference)
        result.update(
            mean_token_f1=sum(scores) / len(scores),
            exact_match=exact / len(records),
            interpretation="lexical single-reference overlap, not empathy or response quality",
        )
    return result
