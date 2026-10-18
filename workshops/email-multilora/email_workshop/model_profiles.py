from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    key: str
    display_name: str
    model_id: str
    revision: str
    target_modules: tuple[str, ...]
    license_name: str
    license_url: str
    notes: str


MODEL_PROFILES = {
    "qwen2.5-0.5b": ModelProfile(
        key="qwen2.5-0.5b",
        display_name="Qwen2.5 0.5B Instruct",
        model_id="Qwen/Qwen2.5-0.5B-Instruct",
        revision="7ae557604adf67be50417f59c2c2f167def9a775",
        target_modules=("q_proj", "v_proj"),
        license_name="Apache-2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct",
        notes="Small default profile for accessible workshop execution.",
    ),
    "nemotron-nano-8b": ModelProfile(
        key="nemotron-nano-8b",
        display_name="Llama 3.1 Nemotron Nano 8B v1",
        model_id="nvidia/Llama-3.1-Nemotron-Nano-8B-v1",
        revision="54641c1611fcff44fa4865626462445e0a153fc7",
        target_modules=("q_proj", "v_proj"),
        license_name="NVIDIA Open Model License",
        license_url=(
            "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/"
        ),
        notes="Validated locally on an RTX 3090 with BF16 and gradient checkpointing.",
    ),
}

DEFAULT_MODEL_PROFILE = "qwen2.5-0.5b"
CUSTOM_MODEL_PROFILE = "custom"


def model_profile_keys() -> tuple[str, ...]:
    return (*MODEL_PROFILES, CUSTOM_MODEL_PROFILE)


def profile_for_model(model_id: str, revision: str) -> ModelProfile | None:
    matches = [
        profile
        for profile in MODEL_PROFILES.values()
        if profile.model_id == model_id and profile.revision == revision
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_model_profile(
    choice: str,
    *,
    model_id: str | None = None,
    revision: str | None = None,
    target_modules: tuple[str, ...] | None = None,
) -> ModelProfile:
    if choice == CUSTOM_MODEL_PROFILE:
        if not model_id or not revision or not target_modules:
            raise ValueError(
                "A custom model requires model_id, immutable revision, and target_modules."
            )
        if any(not item.strip() for item in target_modules) or len(set(target_modules)) != len(
            target_modules
        ):
            raise ValueError("Custom target_modules must contain unique, non-empty module names.")
        return ModelProfile(
            key=CUSTOM_MODEL_PROFILE,
            display_name=model_id,
            model_id=model_id,
            revision=revision,
            target_modules=target_modules,
            license_name="Operator must review",
            license_url="",
            notes="Custom compatible causal language model supplied by the operator.",
        )
    if choice not in MODEL_PROFILES:
        raise ValueError(f"Unknown model profile {choice!r}; choose one of {model_profile_keys()}.")
    if model_id is not None or revision is not None or target_modules is not None:
        raise ValueError(
            "Built-in profiles cannot be partially overridden; use the custom profile."
        )
    return MODEL_PROFILES[choice]
