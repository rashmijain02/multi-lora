"""Local model identity validation, Unsloth loading, and PEFT adapter checks."""

import hashlib
import json
import os
from pathlib import Path

from .paths import ensure_unlinked_path
from .prompts import Hardware, ModelProfile

ADAPTER_WEIGHT_FILES = ("adapter_model.safetensors", "adapter_model.bin")


def adapter_identity(profile: ModelProfile) -> dict:
    return {
        "base_model": profile.model_id,
        "revision": profile.revision,
        "target_modules": sorted(profile.target_modules),
    }


def read_adapter_identity(path: Path) -> dict:
    candidate = ensure_unlinked_path(path)
    meta_path = candidate / "experiment-base.json"
    if not meta_path.is_file():
        raise ValueError(f"Adapter directory is missing experiment-base.json: {candidate.name}")
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or not {"base_model", "revision", "target_modules"} <= set(metadata):
        raise ValueError("Invalid experiment-base.json metadata in adapter directory.")
    return metadata


def check_adapter(path: Path, profile: ModelProfile) -> dict:
    metadata = read_adapter_identity(path)
    if metadata != adapter_identity(profile):
        raise ValueError("This adapter belongs to a different base model, revision, or target set.")
    return metadata


def adapter_fingerprint(path: Path) -> dict[str, str]:
    candidate = ensure_unlinked_path(path)
    required = ["experiment-base.json", "adapter_config.json"]
    weight_file = next((name for name in ADAPTER_WEIGHT_FILES if (candidate / name).is_file()), None)
    if weight_file is None:
        raise ValueError(f"Adapter directory has no saved adapter weights: {candidate.name}")
    required.append(weight_file)
    hashes: dict[str, str] = {}
    for name in required:
        file_path = candidate / name
        if not file_path.is_file():
            raise ValueError(f"Adapter directory is missing '{name}': {candidate.name}")
        hashes[name] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return hashes


def disable_external_telemetry() -> None:
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    os.environ["WANDB_MODE"] = "disabled"
    os.environ["UNSLOTH_DISABLE_STATISTICS"] = "1"


def runtime():
    disable_external_telemetry()
    from unsloth import FastLanguageModel  # noqa: I001
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("The Unsloth backend requires CUDA-enabled PyTorch and an NVIDIA GPU.")
    return torch, FastLanguageModel


def validate_model_targets(model: object, tokenizer: object, profile: ModelProfile) -> None:
    chat_template = getattr(tokenizer, "chat_template", "__unverified__")
    if chat_template != "__unverified__" and not chat_template:
        raise ValueError(f"Selected base model '{profile.model_id}' tokenizer has no chat template.")
    named_modules = getattr(model, "named_modules", None)
    if callable(named_modules):
        entries = list(named_modules())
        if entries:
            available = {name.rsplit(".", 1)[-1] for name, _ in entries if name}
            missing = sorted(set(profile.target_modules) - available)
            if missing:
                raise ValueError(
                    f"Model '{profile.model_id}' is missing configured LoRA target modules: {missing}."
                )


def load_model(
    profile: ModelProfile,
    hardware: Hardware,
    *,
    adapter: Path | None = None,
    is_trainable: bool = False,
    adapter_name: str = "default",
):
    if adapter is not None:
        check_adapter(adapter, profile)
    torch, backend = runtime()
    model, tokenizer = backend.from_pretrained(
        model_name=profile.model_id,
        revision=profile.revision,
        use_exact_model_name=True,
        max_seq_length=hardware.max_length,
        load_in_4bit=hardware.four_bit,
        dtype=torch.bfloat16 if hardware.bf16 else torch.float16,
        trust_remote_code=False,
    )
    validate_model_targets(model, tokenizer, profile)
    if adapter is not None:
        from peft import PeftModel

        kwargs = {"is_trainable": is_trainable}
        if adapter_name != "default":
            kwargs["adapter_name"] = adapter_name
        model = PeftModel.from_pretrained(model, adapter, **kwargs)
    return model, tokenizer
