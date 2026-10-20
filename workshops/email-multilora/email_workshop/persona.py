from __future__ import annotations

import csv
import gc
import hashlib
import json
import os
import re
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

import numpy as np

from email_workshop.data import fingerprint, read_json, write_json
from email_workshop.model_profiles import profile_for_model
from email_workshop.training import (
    CompletionCollator,
    TrainConfig,
    file_hashes,
    train_config_dict,
)

REGISTRY_PATH = Path("config/persona_registry.json")
REQUIRED_COLUMNS = (
    "id",
    "split",
    "subject",
    "body",
    "labels_json",
    "label_count",
    "dataset",
    "dataset_revision",
    "personality_response",
)
SPLITS = ("train", "validation", "test")


class PersonaSpec(TypedDict):
    name: str
    role: str
    adapter: str
    profile_file: str
    data_file: str


class PersonaRow(TypedDict):
    id: str
    split: str
    subject: str
    body: str
    labels_json: str
    label_count: int
    dataset: str
    dataset_revision: str
    personality_response: str


def _safe_workspace_file(workshop_root: Path, relative: str, suffix: str) -> Path:
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or posix.suffix != suffix:
        raise ValueError(f"Registry path must be a relative POSIX {suffix} path: {relative!r}")
    resolved_root = workshop_root.resolve()
    path = (resolved_root / Path(*posix.parts)).resolve()
    if resolved_root not in path.parents:
        raise ValueError(f"Registry path escapes the workshop root: {relative!r}")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def load_persona_registry(workshop_root: Path) -> dict[str, PersonaSpec]:
    registry_file = _safe_workspace_file(workshop_root, REGISTRY_PATH.as_posix(), ".json")
    value = read_json(registry_file)
    if not isinstance(value, dict) or not value:
        raise ValueError("Persona registry must be a non-empty JSON object.")
    adapters: set[str] = set()
    data_files: set[str] = set()
    result: dict[str, PersonaSpec] = {}
    required = {"name", "role", "adapter", "profile_file", "data_file"}
    for client_id, item in value.items():
        if (
            not isinstance(client_id, str)
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", client_id)
            or not isinstance(item, dict)
            or set(item) != required
            or any(not isinstance(item[key], str) or not item[key].strip() for key in required)
        ):
            raise ValueError(f"Invalid persona registry entry: {client_id!r}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item["adapter"]):
            raise ValueError(f"Invalid adapter name for {client_id!r}.")
        _safe_workspace_file(workshop_root, item["profile_file"], ".md")
        _safe_workspace_file(workshop_root, item["data_file"], ".csv")
        if item["adapter"] in adapters or item["data_file"] in data_files:
            raise ValueError("Persona adapter names and data files must be unique.")
        adapters.add(item["adapter"])
        data_files.add(item["data_file"])
        result[client_id] = PersonaSpec(**item)
    return result


def persona_paths(
    workshop_root: Path,
    client_id: str,
    input_file: Path | None = None,
) -> tuple[PersonaSpec, Path, Path]:
    registry = load_persona_registry(workshop_root)
    if client_id not in registry:
        raise ValueError(f"Unknown client {client_id!r}; choose one of {tuple(registry)}.")
    spec = registry[client_id]
    profile_path = _safe_workspace_file(workshop_root, spec["profile_file"], ".md")
    registered_data = _safe_workspace_file(workshop_root, spec["data_file"], ".csv")
    if input_file is not None and input_file.resolve() != registered_data:
        raise ValueError(
            "INPUT_FILE must match the selected registry entry; change CLIENT_ID rather "
            "than pairing one person's profile with another person's responses."
        )
    return spec, profile_path, registered_data


def load_persona_dataset(
    workshop_root: Path,
    client_id: str,
    input_file: Path | None = None,
) -> tuple[dict[str, list[PersonaRow]], PersonaSpec, str, dict[str, Any]]:
    spec, profile_path, data_path = persona_paths(workshop_root, client_id, input_file)
    profile = profile_path.read_text(encoding="utf-8").strip()
    if not profile:
        raise ValueError(f"Persona profile is empty: {profile_path}")
    with data_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError(f"Unexpected persona data schema in {data_path.name}.")
        raw_rows = list(reader)
    rows: list[PersonaRow] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rows, start=1):
        if (
            not raw["id"].strip()
            or raw["id"] in seen
            or raw["split"] not in SPLITS
            or not raw["subject"].strip()
            or not raw["body"].strip()
            or not raw["personality_response"].strip()
        ):
            raise ValueError(f"Invalid persona row {index} in {data_path.name}.")
        try:
            labels = json.loads(raw["labels_json"])
            label_count = int(raw["label_count"])
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"Invalid label fields in row {index}.") from error
        if (
            not isinstance(labels, list)
            or any(not isinstance(label, str) for label in labels)
            or len(labels) != label_count
        ):
            raise ValueError(f"Inconsistent label fields in row {index}.")
        seen.add(raw["id"])
        rows.append(
            {
                **raw,
                "label_count": label_count,
            }
        )
    splits = {name: [row for row in rows if row["split"] == name] for name in SPLITS}
    if any(not splits[name] for name in SPLITS):
        raise ValueError("Persona data must contain non-empty train, validation, and test splits.")
    dataset_sha256 = hashlib.sha256(data_path.read_bytes()).hexdigest()
    profile_sha256 = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    durable_manifest = read_json(data_path.parent / "MANIFEST.json")
    expected = next(
        (item for item in durable_manifest["files"] if item["path"] == data_path.name),
        None,
    )
    if expected is None or expected["sha256"] != dataset_sha256 or expected["rows"] != len(rows):
        raise ValueError("Persona CSV differs from its committed durable manifest.")
    manifest = {
        "client_id": client_id,
        "persona": spec,
        "data_file": spec["data_file"],
        "profile_file": spec["profile_file"],
        "dataset_sha256": dataset_sha256,
        "profile_sha256": profile_sha256,
        "rows": len(rows),
        "split_counts": {name: len(partition) for name, partition in splits.items()},
        "split_ids_sha256": {
            name: fingerprint([row["id"] for row in partition])
            for name, partition in splits.items()
        },
        "task": "persona-conditioned email response generation",
        "test_policy": "sealed until final evaluation",
    }
    return splits, spec, profile, manifest


def persona_messages(
    spec: PersonaSpec,
    profile: str,
    subject: str,
    body: str,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"You write email replies as {spec['name']}, {spec['role']}. "
                "Follow the synthetic workshop profile below. Preserve its communication "
                "style and boundaries without mentioning the profile or claiming actions that "
                "the email does not support. Return only the reply body, with no subject line, "
                f"analysis, or wrapper.\n\nPERSONA PROFILE\n{profile}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"SUBJECT\n{subject}\n\nEMAIL BODY\n{body}\n\n"
                "Write the concise reply this person would send."
            ),
        },
    ]


def persona_prompt_ids(
    tokenizer: Any,
    spec: PersonaSpec,
    profile: str,
    subject: str,
    body: str,
    budget: int,
) -> list[int]:
    if budget < 1:
        raise ValueError("Prompt budget must be positive.")
    subject_tokens = tokenizer.encode(subject, add_special_tokens=False)[:96]
    body_tokens = tokenizer.encode(body, add_special_tokens=False)
    while True:
        messages = persona_messages(
            spec,
            profile,
            tokenizer.decode(subject_tokens, skip_special_tokens=True),
            tokenizer.decode(body_tokens, skip_special_tokens=True),
        )
        prompt = tokenizer.apply_chat_template(
            messages,
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
                "Sequence budget cannot fit the persona profile and chat template. "
                "Increase max_length or shorten the profile."
            )


def persona_training_example(
    tokenizer: Any,
    row: PersonaRow,
    spec: PersonaSpec,
    profile: str,
    max_length: int,
) -> dict[str, list[int]]:
    if tokenizer.eos_token_id is None:
        raise ValueError("Tokenizer must define an EOS token.")
    completion = tokenizer.encode(
        row["personality_response"], add_special_tokens=False
    ) + [tokenizer.eos_token_id]
    if len(completion) >= max_length:
        raise ValueError("Complete target plus EOS must fit without truncation.")
    prompt = persona_prompt_ids(
        tokenizer,
        spec,
        profile,
        row["subject"],
        row["body"],
        max_length - len(completion),
    )
    return {
        "input_ids": prompt + completion,
        "attention_mask": [1] * (len(prompt) + len(completion)),
        "labels": [-100] * len(prompt) + completion,
    }


def _validate_runtime_config(config: TrainConfig) -> None:
    import torch

    if config.device not in ("cuda", "cpu") or config.max_length < 512:
        raise ValueError("device must be cpu/cuda, and persona max_length must be at least 512.")
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
        raise ValueError("Training hyperparameters must be positive.")
    if config.max_steps == 0 or config.max_steps < -1:
        raise ValueError("max_steps must be -1 or a positive number.")
    if config.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable. Use CPU only for a tiny smoke test.")


def train_persona_adapter(
    root: Path,
    workshop_root: Path,
    client_id: str,
    config: TrainConfig,
    input_file: Path | None = None,
) -> dict[str, Any]:
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

    _validate_runtime_config(config)
    splits, spec, profile, data_manifest = load_persona_dataset(
        workshop_root, client_id, input_file
    )
    destination = root / "persona_adapters" / spec["adapter"]
    if destination.exists():
        raise FileExistsError(
            f"{destination} exists. Use a new run root; never overwrite persona adapters."
        )
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
        raise ValueError(f"Model is missing LoRA target modules: {sorted(missing)}.")
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
    selected = splits["train"][: config.sample_limit] if config.sample_limit else splits["train"]
    validation_rows = (
        splits["validation"][: config.sample_limit]
        if config.sample_limit
        else splits["validation"]
    )
    training = [
        persona_training_example(tokenizer, row, spec, profile, config.max_length)
        for row in selected
    ]
    validation = [
        persona_training_example(tokenizer, row, spec, profile, config.max_length)
        for row in validation_rows
    ]

    class LocalTrackioCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs:
                trackio.log(
                    {key: value for key, value in logs.items() if isinstance(value, (int, float))},
                    step=state.global_step,
                )

    training_args = TrainingArguments(
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
        args=training_args,
        train_dataset=training,
        eval_dataset=validation,
        data_collator=CompletionCollator(tokenizer.pad_token_id),
        callbacks=[LocalTrackioCallback()],
    )
    trainable, total = model.get_nb_trainable_parameters()
    trackio.init(
        project="email-persona-lora-local",
        name=f"{root.name}-{spec['adapter']}",
        space_id=None,
        config={**train_config_dict(config), "client_id": client_id},
    )
    started = time.perf_counter()
    try:
        result = trainer.train()
        trainer.save_model(str(destination))
        tokenizer.save_pretrained(destination)
        manifest = {
            "client_id": client_id,
            "adapter": spec["adapter"],
            "persona": spec,
            "config": train_config_dict(config),
            "data_fingerprint": fingerprint(data_manifest),
            "data_manifest": data_manifest,
            "train_rows": len(training),
            "validation_rows": len(validation),
            "training_ids_sha256": fingerprint([row["id"] for row in selected]),
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


def verify_persona_adapter(
    root: Path,
    workshop_root: Path,
    client_id: str,
) -> dict[str, Any]:
    _, spec, _, data_manifest = load_persona_dataset(workshop_root, client_id)
    directory = root / "persona_adapters" / spec["adapter"]
    item = read_json(directory / "manifest.json")
    config = item["config"]
    if "model_profile" not in config or "target_modules" not in config:
        profile = profile_for_model(config["model_id"], config["model_revision"])
        if profile is None:
            raise ValueError("Legacy persona adapter cannot be mapped to a registered model.")
        config = {
            **config,
            "model_profile": profile.key,
            "target_modules": list(profile.target_modules),
        }
    if (
        item["client_id"] != client_id
        or item["adapter"] != spec["adapter"]
        or item["data_fingerprint"] != fingerprint(data_manifest)
    ):
        raise ValueError("Persona adapter identity or data lineage mismatch.")
    if item["files"] != file_hashes(directory):
        raise ValueError("Persona adapter checksum mismatch.")
    return {**item, "config": config}


def installed_persona_adapters(
    root: Path,
    workshop_root: Path,
) -> dict[str, dict[str, Any]]:
    manifests = {}
    for client_id, spec in load_persona_registry(workshop_root).items():
        manifest_path = root / "persona_adapters" / spec["adapter"] / "manifest.json"
        if manifest_path.exists():
            manifests[client_id] = verify_persona_adapter(root, workshop_root, client_id)
    configs = [item["config"] for item in manifests.values()]
    if configs and any(config != configs[0] for config in configs):
        raise ValueError(
            "Persona adapters must share one base/training configuration for Multi-LoRA serving."
        )
    return manifests


def persona_vllm_command(
    root: Path,
    workshop_root: Path,
    linux_run_root: str,
) -> list[str]:
    posix_root = PurePosixPath(linux_run_root)
    if posix_root.is_absolute() or ".." in posix_root.parts:
        raise ValueError("linux_run_root must be a relative POSIX path.")
    manifests = installed_persona_adapters(root, workshop_root)
    if not manifests:
        raise FileNotFoundError("No verified persona adapters are installed.")
    config = next(iter(manifests.values()))["config"]
    return [
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        config["model_id"],
        "--revision",
        config["model_revision"],
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--enable-lora",
        "--max-loras",
        str(len(manifests)),
        "--lora-modules",
        *[
            (
                f"{item['adapter']}="
                f"{posix_root / 'persona_adapters' / item['adapter']}"
            )
            for item in manifests.values()
        ],
    ]


class PersonaBackend:
    def __init__(
        self,
        root: Path,
        workshop_root: Path,
        client_id: str,
        device: str = "cuda",
    ):
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if device not in ("cpu", "cuda"):
            raise ValueError("device must be cpu or cuda.")
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA is unavailable.")
        self.manifest = verify_persona_adapter(root, workshop_root, client_id)
        _, self.spec, self.profile, _ = load_persona_dataset(workshop_root, client_id)
        config = self.manifest["config"]
        directory = root / "persona_adapters" / self.spec["adapter"]
        self.tokenizer = AutoTokenizer.from_pretrained(directory)
        self.max_new_tokens = 192
        self.prompt_budget = config["max_length"] - self.max_new_tokens
        self.device = device
        model = AutoModelForCausalLM.from_pretrained(
            config["model_id"],
            revision=config["model_revision"],
            torch_dtype=(
                torch.bfloat16
                if device == "cuda" and torch.cuda.is_bf16_supported()
                else torch.float32
            ),
            attn_implementation="eager",
        ).to(device)
        self.model = PeftModel.from_pretrained(
            model,
            directory,
            adapter_name=self.spec["adapter"],
        )
        self.model.eval()
        self.model.config.use_cache = True
        self.identity = {
            "backend": "local-persona-peft",
            "device": device,
            "client_id": client_id,
            "adapter_manifest": self.manifest,
            "generation": {"max_new_tokens": self.max_new_tokens, "do_sample": False},
        }

    def generate(self, subject: str, body: str, adapted: bool) -> str:
        import torch

        ids = persona_prompt_ids(
            self.tokenizer,
            self.spec,
            self.profile,
            subject,
            body,
            self.prompt_budget,
        )
        inputs = torch.tensor([ids], device=self.device)
        kwargs = {
            "input_ids": inputs,
            "attention_mask": torch.ones_like(inputs),
            "do_sample": False,
            "max_new_tokens": self.max_new_tokens,
            "pad_token_id": self.tokenizer.pad_token_id,
            "eos_token_id": self.tokenizer.eos_token_id,
        }
        with torch.inference_mode():
            if adapted:
                self.model.set_adapter(self.spec["adapter"])
                output = self.model.generate(**kwargs)
            else:
                with self.model.disable_adapter():
                    output = self.model.generate(**kwargs)
        return self.tokenizer.decode(output[0, len(ids) :], skip_special_tokens=True).strip()


def evaluate_persona(
    rows: list[PersonaRow],
    backend: PersonaBackend,
    mode: str,
    output: Path,
    split_name: str,
) -> list[dict[str, Any]]:
    if mode not in ("base", "adapted") or split_name not in ("validation", "test"):
        raise ValueError("Unknown persona evaluation mode or split.")
    contract = {
        "backend": backend.identity,
        "mode": mode,
        "split": split_name,
        "rows_sha256": fingerprint([row["id"] for row in rows]),
        "version": 1,
    }
    signature = fingerprint(contract)
    results: list[dict[str, Any]] = []
    if output.exists():
        saved = read_json(output)
        if saved["fingerprint"] != signature:
            raise ValueError("Checkpoint belongs to a different persona run or row set.")
        results = saved["predictions"]
        if [item["id"] for item in results] != [
            row["id"] for row in rows[: len(results)]
        ]:
            raise ValueError("Persona checkpoint IDs are not a prefix of the evaluation set.")
    for row in rows[len(results) :]:
        started = time.perf_counter()
        generated = backend.generate(row["subject"], row["body"], adapted=mode == "adapted")
        results.append(
            {
                "id": row["id"],
                "expected": row["personality_response"],
                "generated": generated,
                "valid": bool(generated.strip()),
                "latency_ms": (time.perf_counter() - started) * 1000,
            }
        )
        write_json(
            output,
            {"fingerprint": signature, "contract": contract, "predictions": results},
        )
    return results


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[\w'-]+\b", text.casefold())


def _token_f1(expected: str, generated: str) -> float:
    expected_counts = Counter(_tokens(expected))
    generated_counts = Counter(_tokens(generated))
    overlap = sum((expected_counts & generated_counts).values())
    if not expected_counts and not generated_counts:
        return 1.0
    if not expected_counts or not generated_counts or overlap == 0:
        return 0.0
    precision = overlap / sum(generated_counts.values())
    recall = overlap / sum(expected_counts.values())
    return 2 * precision * recall / (precision + recall)


def _lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            current.append(
                previous[index - 1] + 1
                if left_token == right_token
                else max(previous[index], current[-1])
            )
        previous = current
    return previous[-1]


def score_persona(predictions: list[dict[str, Any]]) -> dict[str, float | int]:
    if not predictions or len({row["id"] for row in predictions}) != len(predictions):
        raise ValueError("Persona scoring needs non-empty predictions with unique IDs.")
    token_f1 = [
        _token_f1(row["expected"], row["generated"]) for row in predictions
    ]
    rouge_l = []
    length_ratios = []
    for row in predictions:
        expected = _tokens(row["expected"])
        generated = _tokens(row["generated"])
        lcs = _lcs_length(expected, generated)
        precision = lcs / len(generated) if generated else 0.0
        recall = lcs / len(expected) if expected else 0.0
        rouge_l.append(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        length_ratios.append(len(generated) / len(expected) if expected else 0.0)
    latencies = [row["latency_ms"] for row in predictions]
    return {
        "rows": len(predictions),
        "nonempty_rate": float(np.mean([row["valid"] for row in predictions])),
        "exact_match": float(
            np.mean(
                [
                    row["expected"].strip() == row["generated"].strip()
                    for row in predictions
                ]
            )
        ),
        "mean_token_f1": float(np.mean(token_f1)),
        "mean_rouge_l": float(np.mean(rouge_l)),
        "mean_length_ratio": float(np.mean(length_ratios)),
        "latency_p50_ms": float(np.percentile(latencies, 50)),
        "latency_p95_ms": float(np.percentile(latencies, 95)),
    }
