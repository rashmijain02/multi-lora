"""Supervised QLoRA training with periodic validation and local telemetry."""

import json
import math
from collections.abc import Callable
from pathlib import Path

from util.models import adapter_identity, check_adapter, load_model, runtime
from util.monitoring import (
    MetricsLogger,
    build_sft_trainer_callback,
    plot_losses,
    plot_sft_diagnostics,
    resolve_eval_steps,
    save_figure,
)
from util.paths import ensure_unlinked_path, restrict_directory
from util.prompts import Hardware, ModelProfile


def collate(examples: list[dict[str, list[int]]], pad: int) -> dict:
    import torch

    width = max(len(row["input_ids"]) for row in examples)
    inputs, masks, labels = [], [], []
    for row in examples:
        length = len(row["input_ids"])
        inputs.append(row["input_ids"] + [pad] * (width - length))
        masks.append([1] * length + [0] * (width - length))
        labels.append(row["labels"] + [-100] * (width - length))
    return {
        key: torch.tensor(value, dtype=torch.long)
        for key, value in (("input_ids", inputs), ("attention_mask", masks), ("labels", labels))
    }


def _backfill_history_if_needed(
    logger: MetricsLogger,
    history: list[dict],
    *,
    total_steps: int,
) -> None:
    if logger.records or not history:
        return
    best_eval: float | None = None
    best_step: int | None = None
    for row in history:
        step = int(row.get("step", 0))
        epoch = float(row["epoch"]) if row.get("epoch") is not None else None
        if "loss" in row and row["loss"] is not None:
            logger.record(
                emit_progress=False,
                event="train_step",
                step=step,
                total_steps=total_steps,
                epoch=epoch,
                loss=float(row["loss"]),
                learning_rate=(
                    float(row["learning_rate"]) if row.get("learning_rate") is not None else None
                ),
                grad_norm=float(row["grad_norm"]) if row.get("grad_norm") is not None else None,
            )
        if "eval_loss" in row and row["eval_loss"] is not None:
            val_loss = float(row["eval_loss"])
            is_best = best_eval is None or val_loss < best_eval
            if is_best:
                best_eval = val_loss
                best_step = step
            logger.record(
                emit_progress=False,
                event="eval",
                step=step,
                total_steps=total_steps,
                epoch=epoch,
                eval_loss=val_loss,
                best_step=best_step,
                is_best=is_best,
            )


def fit(
    model,
    tokenizer,
    profile: ModelProfile,
    hardware: Hardware,
    train: list[dict[str, list[int]]],
    validation: list[dict[str, list[int]]],
    output: Path,
    *,
    seed: int = 42,
    max_steps: int = -1,
    eval_steps: int | None = None,
    notify: Callable[[str], None] | None = None,
) -> tuple[Path, list[dict]]:
    if not train or not validation:
        raise ValueError("Training and validation must each have a complete supervised example.")
    torch_mod, backend = runtime()
    import transformers

    trainer_cls = transformers.Trainer
    args_cls = transformers.TrainingArguments
    callback_base = getattr(transformers, "TrainerCallback", object)

    ensure_unlinked_path(output)
    if not output.exists():
        output.mkdir(mode=0o700, exist_ok=False)
        restrict_directory(output)
    elif not output.is_dir():
        raise ValueError(f"SFT output destination is not a directory: {output.name}")

    steps_per_epoch = max(1, math.ceil(len(train) / (hardware.batch_size * hardware.accumulation)))
    total_steps = max_steps if max_steps > 0 else steps_per_epoch
    effective_eval_steps = resolve_eval_steps(
        eval_steps,
        total_steps=total_steps,
        smoke=(max_steps == 1),
    )

    model = backend.get_peft_model(
        model,
        r=8,
        lora_alpha=16,
        target_modules=list(profile.target_modules),
        use_gradient_checkpointing="unsloth",
        random_state=seed,
    )
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    if pad is None:
        raise ValueError("The tokenizer must provide a padding or EOS token.")

    logger = MetricsLogger(output / "metrics.jsonl", stage="sft", notify=notify)
    callback = build_sft_trainer_callback(
        logger,
        eval_steps=effective_eval_steps,
        total_steps=total_steps,
        run_dir=output,
        torch_mod=torch_mod,
        base_cls=callback_base,
    )

    args = args_cls(
        output_dir=str(output / "checkpoints"),
        num_train_epochs=1,
        max_steps=max_steps,
        per_device_train_batch_size=hardware.batch_size,
        per_device_eval_batch_size=hardware.batch_size,
        gradient_accumulation_steps=hardware.accumulation,
        learning_rate=2e-4,
        optim="adamw_torch",
        bf16=hardware.bf16,
        fp16=not hardware.bf16,
        eval_strategy="steps",
        eval_steps=effective_eval_steps,
        save_strategy="steps",
        save_steps=effective_eval_steps,
        logging_steps=1,
        logging_first_step=True,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=2,
        seed=seed,
        report_to=[],
        push_to_hub=False,
        disable_tqdm=True,
    )
    trainer = trainer_cls(
        model=model,
        args=args,
        train_dataset=train,
        eval_dataset=validation,
        processing_class=tokenizer,
        data_collator=lambda examples: collate(examples, pad),
        callbacks=[callback],
    )
    trainer.train()
    if trainer.state.best_model_checkpoint is None:
        raise RuntimeError("Training ended without a checkpoint selected by validation loss.")

    history = list(trainer.state.log_history)
    _backfill_history_if_needed(logger, history, total_steps=total_steps)
    plot_source = logger.records or history
    save_figure(plot_losses(plot_source), output / "loss.png")
    save_figure(plot_sft_diagnostics(plot_source), output / "training_metrics.png")

    adapter = output / "adapter"
    trainer.save_model(str(adapter))
    (adapter / "experiment-base.json").write_text(
        json.dumps(adapter_identity(profile), indent=2),
        encoding="utf-8",
    )
    return adapter, history


__all__ = [
    "adapter_identity",
    "check_adapter",
    "collate",
    "fit",
    "load_model",
    "runtime",
]
