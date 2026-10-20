from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProfile:
    key: str
    display_name: str
    model_id: str
    revision: str
    target_modules: tuple[str, ...]
    parameters_billions: float
    access: str
    license_name: str
    license_url: str
    notes: str


MODEL_PROFILES = {
    "nemotron-nano-8b": ModelProfile(
        key="nemotron-nano-8b",
        display_name="Llama 3.1 Nemotron Nano 8B v1",
        model_id="nvidia/Llama-3.1-Nemotron-Nano-8B-v1",
        revision="54641c1611fcff44fa4865626462445e0a153fc7",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=8.03,
        access="Public",
        license_name="NVIDIA Open Model License",
        license_url=(
            "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/"
        ),
        notes="Optional larger profile; local 24GB BF16 training is tight and not vendor-certified.",
    ),
    "llama3.1-8b": ModelProfile(
        key="llama3.1-8b",
        display_name="Llama 3.1 8B Instruct",
        model_id="meta-llama/Llama-3.1-8B-Instruct",
        revision="0e9e39f249a16976918f6564b8830bc894c89659",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=8.03,
        access="Gated; accept the Meta license on Hugging Face",
        license_name="Llama 3.1 Community License",
        license_url="https://www.llama.com/llama3_1/license/",
        notes="Popular 8B baseline; download requires an approved Hugging Face account.",
    ),
    "qwen2.5-7b": ModelProfile(
        key="qwen2.5-7b",
        display_name="Qwen2.5 7B Instruct",
        model_id="Qwen/Qwen2.5-7B-Instruct",
        revision="a09a35458c702b33eeacc393d103063234e8bc28",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=7.62,
        access="Public",
        license_name="Apache-2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct",
        notes="Strong public general-purpose alternative near the 8B workshop ceiling.",
    ),
    "mistral-7b-v0.3": ModelProfile(
        key="mistral-7b-v0.3",
        display_name="Mistral 7B Instruct v0.3",
        model_id="mistralai/Mistral-7B-Instruct-v0.3",
        revision="c170c708c41dac9275d15a8fff4eca08d52bab71",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=7.25,
        access="Public",
        license_name="Apache-2.0",
        license_url="https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3",
        notes="Widely used 7B instruct baseline with a standard causal-LM architecture.",
    ),
    "phi-4-mini": ModelProfile(
        key="phi-4-mini",
        display_name="Phi-4 Mini Instruct",
        model_id="microsoft/Phi-4-mini-instruct",
        revision="cfbefacb99257ffa30c83adab238a50856ac3083",
        target_modules=("qkv_proj", "o_proj"),
        parameters_billions=3.84,
        access="Public",
        license_name="MIT",
        license_url="https://huggingface.co/microsoft/Phi-4-mini-instruct",
        notes="Compact Microsoft model; Phi uses fused qkv_proj rather than separate q/v modules.",
    ),
    "qwen2.5-3b": ModelProfile(
        key="qwen2.5-3b",
        display_name="Qwen2.5 3B Instruct",
        model_id="Qwen/Qwen2.5-3B-Instruct",
        revision="aa8e72537993ba99e69dfaafa59ed015b17504d1",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=3.09,
        access="Public",
        license_name="Qwen Research License",
        license_url="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct",
        notes="Mid-size Qwen option; review its model-specific license before use.",
    ),
    "gemma2-2b": ModelProfile(
        key="gemma2-2b",
        display_name="Gemma 2 2B Instruct",
        model_id="google/gemma-2-2b-it",
        revision="299a8560bedf22ed1c72a8a11e7dce4a7f9f51f8",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=2.61,
        access="Gated; accept the Gemma license on Hugging Face",
        license_name="Gemma Terms of Use",
        license_url="https://ai.google.dev/gemma/terms",
        notes="Compact gated option; authenticate with an account that accepted the terms.",
    ),
    "smollm2-1.7b": ModelProfile(
        key="smollm2-1.7b",
        display_name="SmolLM2 1.7B Instruct",
        model_id="HuggingFaceTB/SmolLM2-1.7B-Instruct",
        revision="31b70e2e869a7173562077fd711b654946d38674",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=1.71,
        access="Public",
        license_name="Apache-2.0",
        license_url="https://huggingface.co/HuggingFaceTB/SmolLM2-1.7B-Instruct",
        notes="Small public instruct model for lower-memory experiments.",
    ),
    "qwen2.5-0.5b": ModelProfile(
        key="qwen2.5-0.5b",
        display_name="Qwen2.5 0.5B Instruct",
        model_id="Qwen/Qwen2.5-0.5B-Instruct",
        revision="7ae557604adf67be50417f59c2c2f167def9a775",
        target_modules=("q_proj", "v_proj"),
        parameters_billions=0.49,
        access="Public",
        license_name="Apache-2.0",
        license_url="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct",
        notes="Workshop default for accessible local training and smoke/full workflow iteration.",
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
            parameters_billions=0,
            access="Operator supplied",
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
