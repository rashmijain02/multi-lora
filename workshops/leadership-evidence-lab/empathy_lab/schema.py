"""Prompt and strict JSON output validation shared by SFT and inference."""

from __future__ import annotations

import json
from typing import Any

from .dataset import MECHANISMS, Example


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def output_schema_description() -> str:
    """Return the sole accepted JSON object shape for generated outputs."""
    return (
        '{"emotional_reactions":{"score":0,"rationale":"...","evidence_spans":["..."]},'
        '"interpretations":{"score":0,"rationale":"...","evidence_spans":["..."]},'
        '"explorations":{"score":0,"rationale":"...","evidence_spans":["..."]}}'
    )


def build_prompt(example: Example) -> str:
    """Create a stable prompt that requests scores grounded in verbatim evidence."""
    conversation = "\n".join(f"{turn.role}: {turn.content}" for turn in example.conversation)
    return (
        "Assess only the assistant's support response in this fictional conversation. "
        "These are teaching labels, not a diagnosis or a validated psychometric measure.\n"
        "Score each mechanism as 0 (absent or unsupported), 1 (partial or generic), or "
        "2 (specific and well-supported). Give a concise rationale and quote one or more "
        "exact evidence spans from the conversation for each score. Use no other keys, "
        "no markdown, and exactly this JSON structure:\n"
        f"{output_schema_description()}\n\n"
        f"Conversation:\n{conversation}\n\nJSON:"
    )


def build_messages(
    example: Example, model_id: str, template_options: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    """Build chat messages, keeping the Nemotron reasoning switch in system context."""
    messages = []
    if "nemotron" in model_id.lower() and not template_options:
        messages.append({"role": "system", "content": "detailed thinking off"})
    messages.append({"role": "user", "content": build_prompt(example)})
    return messages


def render_prompt(
    example: Example,
    model_id: str,
    tokenizer: Any,
    template_options: dict[str, Any] | None = None,
) -> str:
    messages = build_messages(example, model_id, template_options)
    if hasattr(tokenizer, "apply_chat_template"):
        return tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, **(template_options or {})
        )
    return build_prompt(example)


def target_json(example: Example) -> str:
    """Serialize human teaching annotations into the inference output format."""
    content = {
        mechanism: {
            "score": example.labels[mechanism].score,
            "rationale": example.labels[mechanism].rationale,
            "evidence_spans": list(example.labels[mechanism].evidence_spans),
        }
        for mechanism in MECHANISMS
    }
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def parse_model_output(raw_output: str, example: Example) -> dict[str, dict[str, Any]]:
    """Parse only the exact schema and evidence grounded in the supplied conversation."""
    source_text = "\n".join(
        turn.content for turn in example.conversation if turn.role == "assistant"
    )
    return parse_evidence_output(raw_output, source_text)


def parse_evidence_output(raw_output: str, source_text: str) -> dict[str, dict[str, Any]]:
    """Validate mechanism predictions against explicitly supplied assistant evidence."""
    if not isinstance(raw_output, str):
        raise TypeError("model output must be a string")
    try:
        parsed = json.loads(raw_output, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"output is not strict JSON: {exc}") from exc
    if not isinstance(parsed, dict) or set(parsed) != set(MECHANISMS):
        raise ValueError(f"output must contain exactly: {', '.join(MECHANISMS)}")
    for mechanism in MECHANISMS:
        value = parsed[mechanism]
        if not isinstance(value, dict) or set(value) != {"score", "rationale", "evidence_spans"}:
            raise ValueError(f"{mechanism} must contain score, rationale, and evidence_spans only")
        score = value["score"]
        if type(score) is not int or score not in (0, 1, 2):
            raise ValueError(f"{mechanism}.score must be the integer 0, 1, or 2")
        rationale = value["rationale"]
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError(f"{mechanism}.rationale must be a non-empty string")
        spans = value["evidence_spans"]
        if (
            not isinstance(spans, list)
            or not spans
            or any(not isinstance(span, str) or not span.strip() for span in spans)
        ):
            raise ValueError(f"{mechanism}.evidence_spans must be a non-empty string list")
        if any(span not in source_text for span in spans):
            raise ValueError(f"{mechanism} contains an evidence span not found in conversation")
    return parsed


def scores_from_output(parsed: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {mechanism: parsed[mechanism]["score"] for mechanism in MECHANISMS}
