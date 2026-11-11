"""Optional Hugging Face causal-LM inference with strict output validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import ModelConfig
from .dataset import Example
from .schema import parse_model_output, render_prompt, scores_from_output


@dataclass(frozen=True)
class GenerationResult:
    example_id: str
    raw_output: str
    scores: dict[str, int] | None
    invalid_reason: str | None

    @property
    def valid(self) -> bool:
        return self.scores is not None


def load_hf_model(config: ModelConfig, adapter_path: str | Path | None = None) -> tuple[Any, Any]:
    """Load a base model and optional LoRA adapter without enabling remote code."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    dtype_map = {
        "auto": "auto",
        "float32": torch.float32,
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }
    tokenizer = AutoTokenizer.from_pretrained(
        config.model_id,
        revision=config.revision,
        use_fast=True,
        trust_remote_code=False,
    )
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ValueError("tokenizer must define either a pad token or EOS token")
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        config.model_id,
        revision=config.revision,
        torch_dtype=dtype_map[config.dtype],
        trust_remote_code=False,
    )
    if adapter_path is not None:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, str(adapter_path))
    if config.device != "auto":
        model.to(config.device)
    model.eval()
    return model, tokenizer


def generate_predictions(
    examples: Sequence[Example],
    config: ModelConfig,
    adapter_path: str | Path | None = None,
    *,
    model: Any | None = None,
    tokenizer: Any | None = None,
) -> list[GenerationResult]:
    """Generate one schema-constrained response per example; failures are not coerced."""
    if (model is None) != (tokenizer is None):
        raise ValueError("provide both model and tokenizer for injected-model inference")
    if model is None:
        model, tokenizer = load_hf_model(config, adapter_path)

    import torch

    device = next(model.parameters()).device
    model.eval()
    results: list[GenerationResult] = []
    previous_padding_side = getattr(tokenizer, "padding_side", "right")
    tokenizer.padding_side = "left"
    try:
        for offset in range(0, len(examples), config.batch_size):
            batch = examples[offset : offset + config.batch_size]
            prompts = [
                render_prompt(example, config.model_id, tokenizer, config.chat_template_kwargs)
                for example in batch
            ]
            encoded = tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=config.max_length,
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with torch.inference_mode():
                generated = model.generate(
                    **encoded,
                    max_new_tokens=config.max_new_tokens,
                    do_sample=False,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                )
            prompt_size = encoded["input_ids"].shape[1]
            for example, continuation in zip(batch, generated[:, prompt_size:], strict=True):
                raw_output = tokenizer.decode(continuation, skip_special_tokens=True).strip()
                try:
                    parsed = parse_model_output(raw_output, example)
                except ValueError as exc:
                    results.append(GenerationResult(example.id, raw_output, None, str(exc)))
                else:
                    results.append(
                        GenerationResult(example.id, raw_output, scores_from_output(parsed), None)
                    )
    finally:
        tokenizer.padding_side = previous_padding_side
    return results
