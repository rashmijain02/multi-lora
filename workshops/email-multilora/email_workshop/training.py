from __future__ import annotations

import gc
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

from email_workshop.data import (
    ADAPTERS,
    allowed_labels,
    fingerprint,
    load_splits,
    messages,
    read_json,
    write_json,
)
from email_workshop.model_profiles import (
    CUSTOM_MODEL_PROFILE,
    DEFAULT_MODEL_PROFILE,
    MODEL_PROFILES,
    profile_for_model,
)

DEFAULT_PROFILE = MODEL_PROFILES[DEFAULT_MODEL_PROFILE]


@dataclass(frozen=True)
class TrainConfig:
    model_profile: str = DEFAULT_PROFILE.key
    model_id: str = DEFAULT_PROFILE.model_id
    model_revision: str = DEFAULT_PROFILE.revision
    target_modules: tuple[str, ...] = DEFAULT_PROFILE.target_modules
    seed: int = 2026
    max_length: int = 512
    rank: int = 8
    epochs: float = 2.0
    learning_rate: float = 2e-4
    batch_size: int = 1
    gradient_accumulation: int = 8
    max_steps: int = -1
    sample_limit: int | None = None
    device: str = "cuda"

    def __post_init__(self) -> None:
        if (
            not self.model_profile.strip()
            or not self.model_id.strip()
            or not self.model_revision.strip()
            or not self.target_modules
            or any(not item.strip() for item in self.target_modules)
        ):
            raise ValueError(
                "Model profile, model ID, immutable revision, and target modules are required."
            )
        if self.model_profile in MODEL_PROFILES:
            profile = MODEL_PROFILES[self.model_profile]
            if (
                self.model_id,
                self.model_revision,
                self.target_modules,
            ) != (
                profile.model_id,
                profile.revision,
                profile.target_modules,
            ):
                raise ValueError(
                    "Built-in model profile details must match the registry exactly; "
                    "use the custom profile for another model."
                )
        elif self.model_profile != CUSTOM_MODEL_PROFILE:
            raise ValueError("model_profile must be a registered profile or custom.")


def train_config_dict(config: TrainConfig) -> dict[str, Any]:
    value = asdict(config)
    value["target_modules"] = list(config.target_modules)
    return value


def prompt_ids(
    tokenizer: Any,
    subject: str,
    body: str,
    labels: tuple[str, ...],
    budget: int,
) -> list[int]:
    subject_tokens = tokenizer.encode(subject, add_special_tokens=False)[:64]
    body_tokens = tokenizer.encode(body, add_special_tokens=False)
    while True:
        prompt = tokenizer.apply_chat_template(
            messages(
                tokenizer.decode(subject_tokens, skip_special_tokens=True),
                tokenizer.decode(body_tokens, skip_special_tokens=True),
                labels,
            ),
            tokenize=True,
            add_generation_prompt=True,
        )
        if len(prompt) <= budget:
            return prompt
        excess = len(prompt) - budget
        if body_tokens:
            body_tokens = body_tokens[: max(0, len(body_tokens) - excess)]
        elif subject_tokens:
            subject_tokens = subject_tokens[: max(0, len(subject_tokens) - excess)]
        else:
            raise ValueError(
                "Sequence budget cannot fit the system instructions and chat template."
            )


def training_example(tokenizer: Any, row: dict[str, Any], adapter: str, max_length: int) -> dict:
    labels = allowed_labels(adapter)
    prompt = prompt_ids(tokenizer, row["subject"], row["body"], labels, max_length - 128)
    target = json.dumps([label for label in labels if label in row["labels"]])
    completion = tokenizer.encode(target, add_special_tokens=False) + [tokenizer.eos_token_id]
    if tokenizer.eos_token_id is None or len(prompt) + len(completion) > max_length:
        raise ValueError("Complete target plus EOS must fit without truncation.")
    return {
        "input_ids": prompt + completion,
        "attention_mask": [1] * (len(prompt) + len(completion)),
        "labels": [-100] * len(prompt) + completion,
    }


class CompletionCollator:
    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, examples: list[dict]) -> dict:
        import torch

        length = max(len(row["input_ids"]) for row in examples)
        return {
            key: torch.tensor([row[key] + [padding] * (length - len(row[key])) for row in examples])
            for key, padding in (
                ("input_ids", self.pad_token_id),
                ("attention_mask", 0),
                ("labels", -100),
            )
        }


def file_hashes(directory: Path) -> dict[str, str]:
    names = (
        "adapter_config.json",
        "adapter_model.safetensors",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    )
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in names}


def train_adapter(root: Path, adapter: str, config: TrainConfig) -> dict[str, Any]:
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    import torch
    import trackio
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        set_seed,
    )

    if adapter not in ADAPTERS:
        raise ValueError(f"Choose one of {ADAPTERS}.")
    if config.device not in ("cuda", "cpu") or config.max_length < 256:
        raise ValueError("device must be cpu/cuda, and max_length must be at least 256.")
    if config.sample_limit is not None and config.sample_limit < 1:
        raise ValueError("sample_limit must be positive.")
    if (
        min(
            config.rank,
            config.epochs,
            config.learning_rate,
            config.batch_size,
            config.gradient_accumulation,
        )
        <= 0
    ):
        raise ValueError(
            "Rank, epochs, learning rate, batch size, and accumulation must be positive."
        )
    if config.max_steps == 0 or config.max_steps < -1:
        raise ValueError("max_steps must be -1 or a positive number.")
    if config.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA is unavailable. Install CUDA PyTorch or use --device cpu for smoke."
        )
    destination = root / "adapters" / adapter
    if destination.exists():
        raise FileExistsError(
            f"{destination} exists. Choose a new run root; never overwrite adapters."
        )
    splits, data_manifest = load_splits(root)
    set_seed(config.seed)
    tokenizer = AutoTokenizer.from_pretrained(config.model_id, revision=config.model_revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    if not tokenizer.chat_template:
        raise ValueError("The base tokenizer must have a chat template.")
    tokenizer.padding_side = "right"
    use_bf16 = config.device == "cuda" and torch.cuda.is_bf16_supported()
    model = AutoModelForCausalLM.from_pretrained(
        config.model_id,
        revision=config.model_revision,
        torch_dtype=torch.bfloat16 if use_bf16 else torch.float32,
        attn_implementation="eager",
    )
    model.config.use_cache = False
    available_modules = {name.rsplit(".", 1)[-1] for name, _ in model.named_modules()}
    if missing := set(config.target_modules) - available_modules:
        raise ValueError(
            f"Model is missing configured LoRA target modules: {sorted(missing)}. "
            "Choose a compatible profile or correct the custom target modules."
        )
    model = get_peft_model(
        model,
        LoraConfig(
            r=config.rank,
            lora_alpha=2 * config.rank,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=list(config.target_modules),
        ),
    )
    selected = splits["train"]
    if config.sample_limit is not None:
        selected = selected[: config.sample_limit]
    training = [training_example(tokenizer, row, adapter, config.max_length) for row in selected]
    validation_rows = splits["validation"]
    if config.sample_limit is not None:
        validation_rows = validation_rows[: config.sample_limit]
    validation = [
        training_example(tokenizer, row, adapter, config.max_length) for row in validation_rows
    ]

    class LocalTrackioCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs:
                trackio.log(
                    {key: value for key, value in logs.items() if isinstance(value, (int, float))},
                    step=state.global_step,
                )

    args = TrainingArguments(
        output_dir=str(destination / "checkpoints"),
        num_train_epochs=config.epochs,
        learning_rate=config.learning_rate,
        per_device_train_batch_size=config.batch_size,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=config.gradient_accumulation,
        max_steps=config.max_steps,
        seed=config.seed,
        data_seed=config.seed,
        use_cpu=config.device == "cpu",
        bf16=use_bf16,
        fp16=False,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        save_total_limit=1,
        logging_steps=1,
        report_to=[],
        push_to_hub=False,
        gradient_checkpointing=config.device == "cuda",
        gradient_checkpointing_kwargs={"use_reentrant": False},
        dataloader_num_workers=0,
        dataloader_pin_memory=config.device == "cuda",
    )
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=training,
        eval_dataset=validation,
        data_collator=CompletionCollator(tokenizer.pad_token_id),
        callbacks=[LocalTrackioCallback()],
    )
    trainable, total = model.get_nb_trainable_parameters()
    trackio.init(
        project="email-multilora-local",
        name=f"{root.name}-{adapter}",
        space_id=None,
        config={**train_config_dict(config), "adapter": adapter},
    )
    started = time.perf_counter()
    try:
        result = trainer.train()
        trainer.save_model(str(destination))
        tokenizer.save_pretrained(destination)
        manifest = {
            "adapter": adapter,
            "config": train_config_dict(config),
            "data_fingerprint": fingerprint(data_manifest),
            "train_rows": len(training),
            "validation_rows": len(validation),
            "training_ids_sha256": fingerprint([row["id"] for row in selected]),
            "allowed_labels": allowed_labels(adapter),
            "purpose": "smoke" if config.max_steps > 0 or config.sample_limit else "workshop",
            "trainable_parameters": trainable,
            "total_parameters": total,
            "elapsed_seconds": time.perf_counter() - started,
            "metrics": result.metrics,
            "history": trainer.state.log_history,
            "best_checkpoint": trainer.state.best_model_checkpoint,
            "files": file_hashes(destination),
            "versions": {name: version(name) for name in ("torch", "transformers", "peft")},
        }
        write_json(destination / "manifest.json", manifest)
    finally:
        trackio.finish()
    del trainer, model
    gc.collect()
    if config.device == "cuda":
        torch.cuda.empty_cache()
    return manifest


def verify_adapters(root: Path) -> dict[str, dict]:
    _, data_manifest = load_splits(root)
    manifests = {}
    for name in ADAPTERS:
        directory = root / "adapters" / name
        item = read_json(directory / "manifest.json")
        config = item["config"]
        if "model_profile" not in config or "target_modules" not in config:
            profile = profile_for_model(config["model_id"], config["model_revision"])
            if profile is None:
                raise ValueError(
                    f"{name} uses a legacy manifest whose model cannot be mapped to a "
                    "registered profile. Retrain or migrate it explicitly."
                )
            item = {
                **item,
                "config": {
                    **config,
                    "model_profile": profile.key,
                    "target_modules": list(profile.target_modules),
                },
            }
        if item["adapter"] != name or item["data_fingerprint"] != fingerprint(data_manifest):
            raise ValueError(f"{name} adapter identity or data lineage mismatch.")
        if item["files"] != file_hashes(directory):
            raise ValueError(f"{name} adapter checksum mismatch.")
        manifests[name] = item
    configs = [item["config"] for item in manifests.values()]
    if any(config != configs[0] for config in configs):
        raise ValueError("Adapters must share the same training/base configuration for comparison.")
    return manifests


class LocalBackend:
    """Sequential PEFT adapter selection on one base, NOT heterogeneous batching."""

    def __init__(self, root: Path, device: str = "cuda"):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if device not in ("cpu", "cuda"):
            raise ValueError("device must be cpu or cuda.")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable.")
        manifests = verify_adapters(root)
        config = manifests["generalist"]["config"]
        self.identity = {
            "backend": "local-peft-sequential",
            "device": device,
            "adapters": manifests,
            "generation": {"max_new_tokens": 128, "do_sample": False},
            "runtime_versions": {name: version(name) for name in ("torch", "transformers", "peft")},
        }
        self.tokenizer = AutoTokenizer.from_pretrained(root / "adapters" / "generalist")
        self.prompt_budget = config["max_length"] - 128
        self.device = device
        model = AutoModelForCausalLM.from_pretrained(
            config["model_id"],
            revision=config["model_revision"],
            torch_dtype=torch.bfloat16
            if device == "cuda" and torch.cuda.is_bf16_supported()
            else torch.float32,
            attn_implementation="eager",
        ).to(device)
        self.model = PeftModel.from_pretrained(
            model,
            root / "adapters" / "generalist",
            adapter_name="generalist",
        )
        for adapter in ADAPTERS[1:]:
            self.model.load_adapter(root / "adapters" / adapter, adapter_name=adapter)
        self.model.eval()
        self.model.config.use_cache = True

    def generate(self, subject: str, body: str, adapter: str) -> str:
        import torch

        labels = allowed_labels(adapter)
        ids = prompt_ids(self.tokenizer, subject, body, labels, self.prompt_budget)
        inputs = torch.tensor([ids], device=self.device)
        kwargs = {
            "input_ids": inputs,
            "attention_mask": torch.ones_like(inputs),
            "do_sample": False,
            "max_new_tokens": 128,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
        }
        with torch.inference_mode():
            if adapter == "base":
                with self.model.disable_adapter():
                    output = self.model.generate(**kwargs)
            else:
                self.model.set_adapter(adapter)
                output = self.model.generate(**kwargs)
        return self.tokenizer.decode(output[0, len(ids) :], skip_special_tokens=True).strip()
