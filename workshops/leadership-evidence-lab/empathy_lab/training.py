"""Explicit LoRA supervised fine-tuning with completion-only loss masking."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .config import ModelConfig
from .dataset import Example
from .inference import load_hf_model
from .schema import render_prompt, target_json


def _training_arguments(config: ModelConfig, output_dir: Path) -> Any:
    from transformers import TrainingArguments

    cadence = min(config.eval_steps, config.max_steps)
    return TrainingArguments(
        output_dir=str(output_dir),
        max_steps=config.max_steps,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=config.batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        learning_rate=config.learning_rate,
        warmup_steps=config.warmup_steps,
        eval_strategy="steps",
        eval_steps=cadence,
        save_strategy="steps",
        save_steps=cadence,
        logging_strategy="steps",
        logging_steps=cadence,
        load_best_model_at_end=False,
        save_total_limit=2,
        seed=config.seed,
        data_seed=config.seed,
        report_to=[],
        remove_unused_columns=False,
        bf16=config.dtype == "bfloat16",
        fp16=config.dtype == "float16" and config.device != "cpu",
        gradient_checkpointing=config.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )


def _training_dataset(
    examples: Sequence[Example],
    tokenizer: Any,
    max_length: int,
    model_id: str,
    template_options: dict[str, Any] | None = None,
) -> Any:
    return completion_dataset(
        [
            (render_prompt(example, model_id, tokenizer, template_options), target_json(example))
            for example in examples
        ],
        tokenizer,
        max_length,
    )


def completion_dataset(pairs: Sequence[tuple[str, str]], tokenizer: Any, max_length: int) -> Any:
    """Mask every prompt token; reject overlength records rather than silently truncating."""
    import torch
    from torch.utils.data import Dataset

    class CompletionOnlyDataset(Dataset):
        def __init__(self) -> None:
            self.items: list[dict[str, list[int]]] = []
            for index, (prompt, target) in enumerate(pairs):
                prompt_ids = tokenizer(
                    prompt,
                    add_special_tokens=False,
                    truncation=False,
                )["input_ids"]
                completion_ids = tokenizer(
                    target,
                    add_special_tokens=False,
                    truncation=False,
                )["input_ids"]
                eos_id = tokenizer.eos_token_id
                if eos_id is not None:
                    completion_ids = [*completion_ids, eos_id]
                if not prompt_ids or not completion_ids:
                    raise ValueError(f"record {index}: prompt and target must tokenize non-empty")
                if len(prompt_ids) + len(completion_ids) > max_length:
                    raise ValueError(
                        f"record {index}: prompt plus target exceeds max_length={max_length}; "
                        "increase the budget or explicitly curate the dataset; no text was truncated"
                    )
                input_ids = prompt_ids + completion_ids
                self.items.append(
                    {
                        "input_ids": input_ids,
                        "attention_mask": [1] * len(input_ids),
                        "labels": [-100] * len(prompt_ids) + completion_ids,
                    }
                )

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            return self.items[index]

    class CompletionOnlyCollator:
        def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, Any]:
            max_batch_length = max(len(item["input_ids"]) for item in features)
            input_ids = torch.full(
                (len(features), max_batch_length),
                tokenizer.pad_token_id,
                dtype=torch.long,
            )
            attention_mask = torch.zeros((len(features), max_batch_length), dtype=torch.long)
            labels = torch.full((len(features), max_batch_length), -100, dtype=torch.long)
            for index, item in enumerate(features):
                length = len(item["input_ids"])
                input_ids[index, :length] = torch.tensor(item["input_ids"], dtype=torch.long)
                attention_mask[index, :length] = 1
                labels[index, :length] = torch.tensor(item["labels"], dtype=torch.long)
            return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}

    return CompletionOnlyDataset(), CompletionOnlyCollator()


def train_lora(
    examples: Sequence[Example],
    config: ModelConfig,
    output_dir: str | Path = "artifacts/lora-adapter",
) -> Any:
    """Train a LoRA adapter using train and validation records only.

    `examples` must contain the train and validation splits, with disjoint scenario
    families. No test examples are accepted or read by the trainer.
    """
    train_examples = [example for example in examples if example.split == "train"]
    validation_examples = [example for example in examples if example.split == "validation"]
    if len(train_examples) + len(validation_examples) != len(examples):
        raise ValueError("LoRA training accepts train and validation examples only")
    if not train_examples or not validation_examples:
        raise ValueError("both train and validation examples are required")
    train_families = {example.scenario_family for example in train_examples}
    validation_families = {example.scenario_family for example in validation_examples}
    if train_families & validation_families:
        raise ValueError("train and validation scenario families must be disjoint")
    destination = Path(output_dir)
    if destination.is_absolute() or ".." in destination.parts:
        raise ValueError("output_dir must be a repository-relative path without parent traversal")

    from transformers import set_seed

    set_seed(config.seed)
    model, tokenizer = load_hf_model(config)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    train_dataset, collator = _training_dataset(
        train_examples, tokenizer, config.max_length, config.model_id, config.chat_template_kwargs
    )
    validation_dataset, _ = _training_dataset(
        validation_examples,
        tokenizer,
        config.max_length,
        config.model_id,
        config.chat_template_kwargs,
    )
    return fit_lora(
        model, tokenizer, config, destination, train_dataset, validation_dataset, collator
    )


def fit_lora(
    model: Any,
    tokenizer: Any,
    config: ModelConfig,
    destination: Path,
    train_dataset: Any,
    validation_dataset: Any,
    collator: Any,
) -> Any:
    """Shared single-device LoRA training engine for independently validated task datasets."""
    from peft import LoraConfig, TaskType, get_peft_model
    from transformers import Trainer

    model.config.use_cache = False
    model = get_peft_model(
        model,
        LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=config.lora_rank,
            lora_alpha=config.lora_alpha,
            lora_dropout=config.lora_dropout,
            target_modules=list(config.lora_target_modules),
        ),
    )
    trainer = Trainer(
        model=model,
        args=_training_arguments(config, destination),
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        data_collator=collator,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(str(destination))
    tokenizer.save_pretrained(str(destination))
    return trainer
