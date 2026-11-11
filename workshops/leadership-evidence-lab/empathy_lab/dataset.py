"""Dataset schema and validation for the fictional support examples."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

MECHANISMS = ("emotional_reactions", "interpretations", "explorations")
SPLITS = ("train", "validation", "test")
DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "fictional_support.jsonl"


class DatasetError(ValueError):
    """Raised when an example violates the workshop dataset contract."""


@dataclass(frozen=True)
class Label:
    score: int
    rationale: str
    evidence_spans: tuple[str, ...]


@dataclass(frozen=True)
class Turn:
    role: str
    content: str


@dataclass(frozen=True)
class Example:
    id: str
    scenario_family: str
    split: str
    conversation: tuple[Turn, ...]
    labels: dict[str, Label]

    @property
    def conversation_text(self) -> str:
        return "\n".join(f"{turn.role}: {turn.content}" for turn in self.conversation)


def _require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        missing = expected - set(value)
        unknown = set(value) - expected
        details = []
        if missing:
            details.append(f"missing {', '.join(sorted(missing))}")
        if unknown:
            details.append(f"unknown {', '.join(sorted(unknown))}")
        raise DatasetError(f"{context}: " + "; ".join(details))


def _parse_example(raw: Any, line_number: int) -> Example:
    context = f"line {line_number}"
    if not isinstance(raw, dict):
        raise DatasetError(f"{context}: each JSONL item must be an object")
    _require_exact_keys(
        raw,
        {"id", "fictional", "scenario_family", "split", "conversation", "labels"},
        context,
    )
    if raw["fictional"] is not True:
        raise DatasetError(f"{context}: fictional must be true; real-person data is not allowed")
    for field in ("id", "scenario_family"):
        if not isinstance(raw[field], str) or not raw[field].strip():
            raise DatasetError(f"{context}: {field} must be a non-empty string")
    if raw["split"] not in SPLITS:
        raise DatasetError(f"{context}: split must be one of {', '.join(SPLITS)}")

    raw_turns = raw["conversation"]
    if not isinstance(raw_turns, list) or len(raw_turns) < 2:
        raise DatasetError(f"{context}: conversation must contain at least two turns")
    turns: list[Turn] = []
    for turn_number, turn in enumerate(raw_turns, start=1):
        turn_context = f"{context}, turn {turn_number}"
        if not isinstance(turn, dict):
            raise DatasetError(f"{turn_context}: turn must be an object")
        _require_exact_keys(turn, {"role", "content"}, turn_context)
        if not isinstance(turn["role"], str) or turn["role"] not in {"user", "assistant"}:
            raise DatasetError(f"{turn_context}: role must be user or assistant")
        if not isinstance(turn["content"], str) or not turn["content"].strip():
            raise DatasetError(f"{turn_context}: content must be a non-empty string")
        turns.append(Turn(turn["role"], turn["content"]))
    if turns[0].role != "user" or turns[-1].role != "assistant":
        raise DatasetError(f"{context}: conversation must start with user and end with assistant")
    if any(left.role == right.role for left, right in pairwise(turns)):
        raise DatasetError(f"{context}: conversation turns must alternate user and assistant")

    if not isinstance(raw["labels"], dict):
        raise DatasetError(f"{context}: labels must be an object")
    _require_exact_keys(raw["labels"], set(MECHANISMS), f"{context}, labels")
    assistant_text = "\n".join(turn.content for turn in turns if turn.role == "assistant")
    labels: dict[str, Label] = {}
    for mechanism in MECHANISMS:
        annotation = raw["labels"][mechanism]
        label_context = f"{context}, {mechanism}"
        if not isinstance(annotation, dict):
            raise DatasetError(f"{label_context}: annotation must be an object")
        _require_exact_keys(annotation, {"score", "rationale", "evidence_spans"}, label_context)
        score = annotation["score"]
        if type(score) is not int or score not in (0, 1, 2):
            raise DatasetError(f"{label_context}: score must be the integer 0, 1, or 2")
        rationale = annotation["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise DatasetError(f"{label_context}: rationale must be a non-empty string")
        evidence = annotation["evidence_spans"]
        if not isinstance(evidence, list) or not evidence:
            raise DatasetError(f"{label_context}: evidence_spans must be a non-empty list")
        if any(not isinstance(span, str) or not span.strip() for span in evidence):
            raise DatasetError(f"{label_context}: each evidence span must be a non-empty string")
        if any(span not in assistant_text for span in evidence):
            raise DatasetError(
                f"{label_context}: every evidence span must occur verbatim in assistant text"
            )
        labels[mechanism] = Label(score, rationale, tuple(evidence))

    return Example(
        id=raw["id"],
        scenario_family=raw["scenario_family"],
        split=raw["split"],
        conversation=tuple(turns),
        labels=labels,
    )


def validate_examples(
    examples: Iterable[Example], *, require_all_splits: bool = True
) -> list[Example]:
    """Check unique IDs, split completeness, and scenario-family disjointness."""
    result = list(examples)
    if not result:
        raise DatasetError("dataset must contain at least one example")
    ids: set[str] = set()
    family_splits: dict[str, str] = {}
    found_splits: set[str] = set()
    for example in result:
        if example.id in ids:
            raise DatasetError(f"duplicate example id: {example.id}")
        ids.add(example.id)
        found_splits.add(example.split)
        previous = family_splits.setdefault(example.scenario_family, example.split)
        if previous != example.split:
            raise DatasetError(
                f"scenario family {example.scenario_family!r} occurs in multiple splits"
            )
    missing = set(SPLITS) - found_splits
    if require_all_splits and missing:
        raise DatasetError(f"dataset missing split(s): {', '.join(sorted(missing))}")
    return result


def load_dataset(path: str | Path = DEFAULT_DATA_PATH) -> list[Example]:
    """Read and strictly validate a JSONL dataset; defaults to the bundled fictional set."""
    parsed: list[Example] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise DatasetError(f"line {line_number}: blank lines are not allowed")
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            parsed.append(_parse_example(raw, line_number))
    return validate_examples(parsed)
