from pathlib import Path

import pytest

from email_workshop.model_profiles import MODEL_PROFILES
from email_workshop.persona_pipeline import (
    DEFAULT_PERSONA_MODEL_PROFILE,
    PersonaPipelineConfig,
    public_config,
)


def test_persona_pipeline_uses_local_three_billion_parameter_model():
    profile = MODEL_PROFILES[DEFAULT_PERSONA_MODEL_PROFILE]
    assert DEFAULT_PERSONA_MODEL_PROFILE == "qwen2.5-3b"
    assert profile.parameters_billions < 4
    assert profile.access == "Public"
    assert profile.target_modules == ("q_proj", "v_proj")


def test_persona_pipeline_config_is_serializable(tmp_path):
    profile = MODEL_PROFILES[DEFAULT_PERSONA_MODEL_PROFILE]
    config = PersonaPipelineConfig(
        workshop_root=Path(__file__).resolve().parents[1],
        root=tmp_path / "run",
        model_profile=profile.key,
        model_id=profile.model_id,
        model_revision=profile.revision,
        target_modules=profile.target_modules,
        clients=("maya-chen-ceo",),
    )
    value = public_config(config)
    assert value["model_profile"] == "qwen2.5-3b"
    assert value["max_length"] == 1024
    assert value["epochs"] == 1.0
    assert value["clients"] == ["maya-chen-ceo"]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("device", "metal", "device"),
        ("max_length", 256, "max_length"),
        ("epochs", 0, "positive"),
        ("max_steps", 0, "max_steps"),
        ("evaluation_limit", 0, "positive"),
    ],
)
def test_persona_pipeline_rejects_invalid_configuration(
    tmp_path, field, value, message
):
    profile = MODEL_PROFILES[DEFAULT_PERSONA_MODEL_PROFILE]
    kwargs = {
        "workshop_root": Path(__file__).resolve().parents[1],
        "root": tmp_path / "run",
        "model_profile": profile.key,
        "model_id": profile.model_id,
        "model_revision": profile.revision,
        "target_modules": profile.target_modules,
        field: value,
    }
    with pytest.raises(ValueError, match=message):
        PersonaPipelineConfig(**kwargs)
