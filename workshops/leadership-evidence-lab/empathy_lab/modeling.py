"""Notebook-facing HF inference and LoRA training APIs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import ModelConfig
from .data import as_examples
from .dataset import Example
from .inference import GenerationResult, generate_predictions
from .training import train_lora


def _resolve_config(config: ModelConfig | str | Path) -> ModelConfig:
    return config if isinstance(config, ModelConfig) else ModelConfig.from_json(config)


def predict_detailed(
    config: ModelConfig | str | Path,
    records: Sequence[Example | dict[str, Any]],
    adapter_path: str | Path | None = None,
    *,
    model: Any | None = None,
    tokenizer: Any | None = None,
) -> list[GenerationResult]:
    """Return decoded outputs and reasons for invalid model generations."""
    examples = as_examples(records)
    return generate_predictions(
        examples,
        _resolve_config(config),
        adapter_path,
        model=model,
        tokenizer=tokenizer,
    )


def save_generation_report(
    results: Sequence[GenerationResult],
    config: ModelConfig,
    report_path: str | Path,
    adapter_path: str | Path | None = None,
) -> Path:
    """Write a portable JSON report with model revision and per-record validity."""
    path = Path(report_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("report_path must be repository-relative without parent traversal")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_id": config.model_id,
        "revision": config.revision,
        "device": config.device,
        "dtype": config.dtype,
        "adapter_path": str(adapter_path) if adapter_path is not None else None,
        "generation_parameters": {
            "max_new_tokens": config.max_new_tokens,
            "max_length": config.max_length,
            "batch_size": config.batch_size,
            "seed": config.seed,
        },
        "results": [
            {
                "example_id": result.example_id,
                "raw_output": result.raw_output,
                "scores": result.scores,
                "valid": result.valid,
                "invalid_reason": result.invalid_reason,
            }
            for result in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def predict(
    config: ModelConfig | str | Path,
    records: Sequence[Example | dict[str, Any]],
    adapter_path: str | Path | None = None,
    *,
    report_path: str | Path | None = None,
    model: Any | None = None,
    tokenizer: Any | None = None,
) -> dict[str, dict[str, int] | None]:
    """Return `{example_id: scores | None}`; malformed generations remain invalid.

    Set `report_path` to preserve raw output and model provenance; use
    `predict_detailed` when notebook code needs to inspect generation failures.
    """
    resolved = _resolve_config(config)
    results = predict_detailed(resolved, records, adapter_path, model=model, tokenizer=tokenizer)
    if report_path is not None:
        save_generation_report(results, resolved, report_path, adapter_path)
    return {result.example_id: result.scores for result in results}


def train(
    config: ModelConfig | str | Path,
    train_records: Sequence[Example | dict[str, Any]],
    validation_records: Sequence[Example | dict[str, Any]],
    output_dir: str | Path = "artifacts/lora-adapter",
) -> Any:
    """Train one LoRA adapter on train data and validate only on validation data."""
    train_examples = as_examples(train_records)
    validation_examples = as_examples(validation_records)
    if any(example.split != "train" for example in train_examples):
        raise ValueError("train_records must contain train split records only")
    if any(example.split != "validation" for example in validation_examples):
        raise ValueError("validation_records must contain validation split records only")
    combined = as_examples([*train_examples, *validation_examples])
    return train_lora(combined, _resolve_config(config), output_dir)
