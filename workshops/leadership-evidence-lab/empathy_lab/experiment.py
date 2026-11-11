"""Shared, aggregate-only experiment CLI for three deliberately distinct learning tasks."""

from __future__ import annotations

import argparse
import json
import math
import platform
import time
from collections import Counter
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from .corpora import (
    ExperimentConfig,
    canonical_hash,
    load_experiment,
    load_prepared,
    prepare,
)
from .dataset import MECHANISMS
from .tasks import TaskRecord, parse_prediction, render_messages, task_metrics


def _tokenizer(config: ExperimentConfig) -> Any:
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        config.model.model_id,
        revision=config.model.revision,
        trust_remote_code=False,
    )
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise ValueError("tokenizer must have an EOS or pad token")
        tokenizer.pad_token = tokenizer.eos_token
    return tokenizer


def _pairs(records: list[TaskRecord], config: ExperimentConfig, tokenizer: Any) -> list:
    return [
        (
            render_messages(
                item, tokenizer, config.model.model_id, config.model.chat_template_kwargs
            ),
            item.target,
        )
        for item in records
    ]


def validate(config: ExperimentConfig, *, tokens: bool = False) -> dict[str, Any]:
    records, manifest = load_prepared(config)
    report = {
        "task": config.task,
        "data_fingerprint": manifest["data_fingerprint"],
        "source_counts": manifest["source_counts"],
        "selected_counts": manifest["selected_counts"],
        "dropped_cross_split_duplicate_inputs": manifest["dropped_cross_split_duplicate_inputs"],
        "source": manifest["source"],
    }
    if tokens:
        tokenizer = _tokenizer(config)
        from .training import completion_dataset

        dataset, _ = completion_dataset(
            _pairs(records, config, tokenizer), tokenizer, config.model.max_length
        )
        lengths = [len(item["input_ids"]) for item in dataset]
        prompt_lengths = [sum(label == -100 for label in item["labels"]) for item in dataset]
        if max(prompt_lengths) + config.model.max_new_tokens > config.model.max_length:
            raise ValueError(
                "prompt plus generation budget exceeds max_length; no text was truncated"
            )
        report["tokens"] = {
            "min_training_length": min(lengths),
            "max_training_length": max(lengths),
            "max_prompt_length": max(prompt_lengths),
            "truncation": "none",
        }
    return report


def _save_report(directory: Path, name: str, report: dict) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    if path.exists():
        raise FileExistsError("report already exists; choose a different --run name")
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def _provenance(config: ExperimentConfig, manifest: dict) -> dict[str, Any]:
    return {
        "task": config.task,
        "model": asdict(config.model),
        "data_fingerprint": manifest["data_fingerprint"],
        "selected_counts": manifest["selected_counts"],
        "purpose": "bounded engineering verification, not a quality claim",
    }


def baseline(config: ExperimentConfig, split: str, *, run: str | None = None) -> dict:
    if split not in {"validation", "test"}:
        raise ValueError("evaluate validation or test, never train")
    records, manifest = load_prepared(config, ("train", split))
    training = [item for item in records if item.split == "train"]
    evaluation = [item for item in records if item.split == split]
    if config.task == "empathetic_dialogues":
        common = Counter(item.target for item in training).most_common(1)[0][0]
        predictions = [common] * len(evaluation)
        method = "most frequent training response; lexical control, not a good support agent"
    else:
        import numpy as np
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression

        vectorizer = TfidfVectorizer(ngram_range=(1, 2), max_features=20000)
        features = vectorizer.fit_transform([item.messages[-1]["content"] for item in training])
        evaluation_features = vectorizer.transform(
            [item.messages[-1]["content"] for item in evaluation]
        )
        gold = [parse_prediction(config.task, item.target, item) for item in training]
        columns = list(MECHANISMS) if config.task == "fictional_empathy" else list(range(28))
        outputs = []
        for column in columns:
            target = (
                [item[column] for item in gold]
                if config.task == "fictional_empathy"
                else [int(column in item) for item in gold]
            )
            if len(set(target)) == 1:
                output = np.full(len(evaluation), target[0])
            else:
                head = LogisticRegression(
                    class_weight="balanced", max_iter=500, random_state=config.seed
                )
                head.fit(features, target)
                output = (
                    head.predict(evaluation_features)
                    if config.task == "fictional_empathy"
                    else head.predict_proba(evaluation_features)[:, 1]
                )
            outputs.append(output)
        if config.task == "fictional_empathy":
            predictions = [
                {name: int(outputs[j][i]) for j, name in enumerate(MECHANISMS)}
                for i in range(len(evaluation))
            ]
        else:
            probabilities = np.array(outputs).T
            predictions = [
                np.flatnonzero(row >= 0.5).tolist() or [int(row.argmax())] for row in probabilities
            ]
        method = (
            "train-only TF-IDF and balanced logistic heads; emotion threshold 0.5, argmax fallback"
        )
    return _save_report(
        config.run_dir(run),
        f"baseline-{split}.json",
        {
            **_provenance(config, manifest),
            "split": split,
            "method": method,
            "metrics": task_metrics(config.task, evaluation, predictions),
        },
    )


def _environment(model: Any) -> dict[str, Any]:
    import torch

    device = next(model.parameters()).device
    return {
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("torch", "transformers", "peft")},
        "device": str(device),
        "cuda_runtime": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
    }


def train(config: ExperimentConfig, *, run: str | None = None) -> dict:
    """Only train and validation files are opened; test content is never read."""
    import torch
    from transformers import set_seed

    from .inference import load_hf_model
    from .training import completion_dataset, fit_lora

    directory = config.run_dir(run)
    destination = directory / "adapter"
    if destination.exists() or (directory / "training.json").exists():
        raise FileExistsError("training output exists; choose a new --run name")
    records, manifest = load_prepared(config, ("train", "validation"))
    set_seed(config.model.seed)
    model, tokenizer = load_hf_model(config.model)
    datasets = {}
    for split in ("train", "validation"):
        items = [item for item in records if item.split == split]
        datasets[split], collator = completion_dataset(
            _pairs(items, config, tokenizer),
            tokenizer,
            config.model.max_length,
        )
    if next(model.parameters()).is_cuda:
        torch.cuda.reset_peak_memory_stats(next(model.parameters()).device)
    started = time.monotonic()
    trainer = fit_lora(
        model,
        tokenizer,
        config.model,
        destination,
        datasets["train"],
        datasets["validation"],
        collator,
    )
    elapsed = time.monotonic() - started
    report = {
        **_provenance(config, manifest),
        "environment": _environment(model),
        "steps": trainer.state.global_step,
        "training_seconds": elapsed,
        "peak_cuda_allocated_bytes": (
            torch.cuda.max_memory_allocated(next(model.parameters()).device)
            if next(model.parameters()).is_cuda
            else None
        ),
        "metrics": [
            {
                key: value
                for key, value in item.items()
                if key in {"loss", "eval_loss", "train_loss", "step", "epoch"}
            }
            for item in trainer.state.log_history
        ],
    }
    return _save_report(directory, "training.json", report)


def _loss(model: Any, dataset: Any, collator: Any, batch_size: int) -> dict[str, Any]:
    import torch

    total_loss = 0.0
    total_tokens = 0
    device = next(model.parameters()).device
    with torch.inference_mode():
        for offset in range(0, len(dataset), batch_size):
            batch = collator(
                [dataset[i] for i in range(offset, min(offset + batch_size, len(dataset)))]
            )
            batch = {key: value.to(device) for key, value in batch.items()}
            tokens = (batch["labels"][:, 1:] != -100).sum().item()
            value = model(**batch).loss.item()
            if not math.isfinite(value):
                raise ValueError("non-finite teacher-forced loss")
            total_loss += value * tokens
            total_tokens += tokens
    mean = total_loss / total_tokens
    return {
        "target_token_nll": mean,
        "target_tokens": total_tokens,
        "target_token_perplexity": math.exp(mean) if mean < 700 else None,
    }


def evaluate(
    config: ExperimentConfig,
    split: str,
    *,
    adapted: bool = False,
    run: str | None = None,
) -> dict:
    if split not in {"validation", "test"}:
        raise ValueError("evaluate validation or test, never train")
    import torch
    from transformers import set_seed

    from .inference import load_hf_model
    from .training import completion_dataset

    records, manifest = load_prepared(config, (split,))
    directory = config.run_dir(run)
    name = f"{'adapted' if adapted else 'base'}-{split}.json"
    if (directory / name).exists():
        raise FileExistsError("evaluation report exists; choose a new --run name")
    adapter = directory / "adapter" if adapted else None
    if adapted:
        training = json.loads((directory / "training.json").read_text(encoding="utf-8"))
        for key in ("task", "model", "data_fingerprint"):
            if canonical_hash(training[key]) != canonical_hash(_provenance(config, manifest)[key]):
                raise ValueError("adapter task/model/data provenance mismatch")
    set_seed(config.model.seed)
    model, tokenizer = load_hf_model(config.model, adapter)
    pairs = _pairs(records, config, tokenizer)
    dataset, collator = completion_dataset(pairs, tokenizer, config.model.max_length)
    loss = _loss(model, dataset, collator, config.model.batch_size)
    tokenizer.padding_side = "left"
    model.config.use_cache = True
    device = next(model.parameters()).device
    predictions = []
    reasons: Counter[str] = Counter()
    generated_tokens = 0
    started = time.monotonic()
    for offset in range(0, len(records), config.model.batch_size):
        batch_records = records[offset : offset + config.model.batch_size]
        prompts = [pair[0] for pair in pairs[offset : offset + config.model.batch_size]]
        encoded = tokenizer(
            prompts, padding=True, truncation=False, return_tensors="pt", add_special_tokens=False
        )
        size = encoded["input_ids"].shape[1]
        if size + config.model.max_new_tokens > config.model.max_length:
            raise ValueError(
                "prompt plus generation budget exceeds max_length; no text was truncated"
            )
        encoded = {key: value.to(device) for key, value in encoded.items()}
        with torch.inference_mode():
            generated = model.generate(
                **encoded,
                max_new_tokens=config.model.max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        for record, continuation in zip(batch_records, generated[:, size:], strict=True):
            generated_tokens += sum(
                token != tokenizer.pad_token_id for token in continuation.tolist()
            )
            raw = tokenizer.decode(continuation, skip_special_tokens=True).strip()
            try:
                predictions.append(parse_prediction(config.task, raw, record))
            except (ValueError, TypeError):
                predictions.append(None)
                reasons["invalid_output_contract"] += 1
    return _save_report(
        directory,
        name,
        {
            **_provenance(config, manifest),
            "environment": _environment(model),
            "split": split,
            "adapted": adapted,
            "metrics": task_metrics(config.task, records, predictions),
            "teacher_forced": loss,
            "invalid_reasons": dict(reasons),
            "generation_seconds": time.monotonic() - started,
            "generated_tokens": generated_tokens,
            "privacy": "aggregate only; no source text, identifiers, references, or generations",
        },
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m empathy_lab experiment")
    parser.add_argument("action", choices=("prepare", "validate", "baseline", "train", "evaluate"))
    parser.add_argument(
        "--config", required=True, help="experiment JSON; model profile is reusable"
    )
    parser.add_argument("--download", action="store_true", help="explicit public-data acquisition")
    parser.add_argument("--tokens", action="store_true", help="validate model token budgets")
    parser.add_argument("--split", choices=("validation", "test"), default="validation")
    parser.add_argument("--adapted", action="store_true", help="load this run's verified adapter")
    parser.add_argument(
        "--run", help="distinct local run name; existing reports are never overwritten"
    )
    args = parser.parse_args(argv)
    config = load_experiment(args.config)
    if args.download and args.action != "prepare":
        parser.error("--download is only permitted for prepare")
    if args.tokens and args.action != "validate":
        parser.error("--tokens is only permitted for validate")
    if args.adapted and args.action != "evaluate":
        parser.error("--adapted is only permitted for evaluate")
    if args.action == "prepare":
        report = prepare(config, download=args.download)
    elif args.action == "validate":
        report = validate(config, tokens=args.tokens)
    elif args.action == "baseline":
        report = baseline(config, args.split, run=args.run)
    elif args.action == "train":
        report = train(config, run=args.run)
    else:
        report = evaluate(config, args.split, adapted=args.adapted, run=args.run)
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0
