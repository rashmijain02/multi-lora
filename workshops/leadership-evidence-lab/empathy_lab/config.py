"""Strict, flat model-profile loading shared by inference and training."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    revision: str
    device: str = "cuda"
    dtype: str = "float16"
    max_new_tokens: int = 160
    max_length: int = 1024
    batch_size: int = 1
    learning_rate: float = 2e-4
    max_steps: int = 100
    lora_rank: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    lora_target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    gradient_accumulation_steps: int = 1
    warmup_steps: int = 0
    eval_steps: int = 10
    seed: int = 17
    gradient_checkpointing: bool = False
    chat_template_kwargs: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: str | Path) -> ModelConfig:
        """Load a flat JSON model profile."""
        return load_config(path)


def _positive_int(name: str, value: Any, *, allow_zero: bool = False) -> None:
    if type(value) is not int or value < (0 if allow_zero else 1):
        requirement = "a non-negative integer" if allow_zero else "a positive integer"
        raise ValueError(f"{name} must be {requirement}")


def config_from_mapping(raw: dict[str, Any]) -> ModelConfig:
    """Validate a flat profile; unknown keys and implicit coercions are rejected."""
    profile_fields = {
        "model_id",
        "revision",
        "device",
        "dtype",
        "max_new_tokens",
        "max_length",
        "batch_size",
        "learning_rate",
        "max_steps",
        "lora_rank",
        "seed",
        "gradient_accumulation_steps",
    }
    allowed = {item.name for item in fields(ModelConfig)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown model profile field(s): {', '.join(sorted(unknown))}")
    missing = profile_fields - set(raw)
    if missing:
        raise ValueError(f"missing required model profile field(s): {', '.join(sorted(missing))}")

    values = dict(raw)
    for name in ("model_id", "revision", "device", "dtype"):
        if name in values and (not isinstance(values[name], str) or not values[name].strip()):
            raise ValueError(f"{name} must be a non-empty string")

    revision = values["revision"].strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        raise ValueError("revision must be a 40-character immutable model commit hash")
    values["revision"] = revision

    if "dtype" in values and values["dtype"] not in {
        "auto",
        "float32",
        "float16",
        "bfloat16",
    }:
        raise ValueError("dtype must be auto, float32, float16, or bfloat16")
    if (
        "device" in values
        and values["device"] != "auto"
        and values["device"] not in {"cpu", "cuda"}
        and not re.fullmatch(r"cuda:\d+", values["device"])
    ):
        raise ValueError("device must be auto, cpu, cuda, or a cuda device such as cuda:0")

    for name in (
        "max_new_tokens",
        "max_length",
        "batch_size",
        "max_steps",
        "lora_rank",
        "lora_alpha",
        "gradient_accumulation_steps",
        "eval_steps",
    ):
        if name in values:
            _positive_int(name, values[name])
    if "warmup_steps" in values:
        _positive_int("warmup_steps", values["warmup_steps"], allow_zero=True)
    if "seed" in values:
        _positive_int("seed", values["seed"], allow_zero=True)
    if values.get("max_new_tokens", 160) >= values.get("max_length", 1024):
        raise ValueError("max_new_tokens must be smaller than max_length")
    if "learning_rate" in values:
        learning_rate = values["learning_rate"]
        if isinstance(learning_rate, bool) or not isinstance(learning_rate, (int, float)):
            raise ValueError("learning_rate must be a positive number")
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be a positive number")
        values["learning_rate"] = float(learning_rate)
    if "lora_dropout" in values:
        dropout = values["lora_dropout"]
        if isinstance(dropout, bool) or not isinstance(dropout, (int, float)):
            raise ValueError("lora_dropout must be between 0 and 1")
        if not 0 <= dropout < 1:
            raise ValueError("lora_dropout must be between 0 and 1")
        values["lora_dropout"] = float(dropout)
    if "lora_target_modules" in values:
        targets = values["lora_target_modules"]
        if (
            not isinstance(targets, list)
            or not targets
            or any(not isinstance(target, str) or not target.strip() for target in targets)
        ):
            raise ValueError("lora_target_modules must be a non-empty list of module names")
        values["lora_target_modules"] = tuple(targets)
    if "gradient_checkpointing" in values and type(values["gradient_checkpointing"]) is not bool:
        raise ValueError("gradient_checkpointing must be a boolean")
    if "chat_template_kwargs" in values:
        options = values["chat_template_kwargs"]
        if not isinstance(options, dict) or set(options) - {"enable_thinking", "reasoning_effort"}:
            raise ValueError("chat_template_kwargs supports enable_thinking and reasoning_effort")
        if "enable_thinking" in options and type(options["enable_thinking"]) is not bool:
            raise ValueError("enable_thinking must be a boolean")
        if "reasoning_effort" in options and options["reasoning_effort"] not in {
            "none",
            "low",
            "medium",
            "high",
        }:
            raise ValueError("reasoning_effort must be none, low, medium, or high")

    return ModelConfig(**values)


def load_config(path: str | Path) -> ModelConfig:
    """Load a UTF-8 flat JSON profile, rejecting malformed JSON and unknown fields."""
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise TypeError("model profile must be a JSON object")
    return config_from_mapping(raw)
