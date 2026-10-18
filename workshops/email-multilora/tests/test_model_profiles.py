import pytest

from email_workshop.model_profiles import (
    DEFAULT_MODEL_PROFILE,
    MODEL_PROFILES,
    model_profile_keys,
    profile_for_model,
    resolve_model_profile,
)
from email_workshop.training import TrainConfig, train_config_dict


def test_default_profile_is_complete_and_pinned():
    profile = resolve_model_profile(DEFAULT_MODEL_PROFILE)
    assert profile == MODEL_PROFILES[DEFAULT_MODEL_PROFILE]
    assert len(profile.revision) == 40
    assert profile.target_modules
    assert profile.license_name and profile.license_url


def test_built_in_profiles_are_not_partially_overridden():
    with pytest.raises(ValueError, match="custom"):
        resolve_model_profile(DEFAULT_MODEL_PROFILE, model_id="another/model")


def test_custom_profile_requires_complete_configuration():
    with pytest.raises(ValueError, match="requires"):
        resolve_model_profile("custom", model_id="example/model", revision="immutable")

    profile = resolve_model_profile(
        "custom",
        model_id="example/model",
        revision="immutable",
        target_modules=("query", "value"),
    )
    assert profile.key == "custom"
    assert profile.target_modules == ("query", "value")


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        resolve_model_profile("not-a-profile")


def test_profile_keys_include_builtins_and_custom():
    assert set(MODEL_PROFILES) < set(model_profile_keys())
    assert "custom" in model_profile_keys()


def test_pinned_model_can_be_mapped_for_legacy_manifests():
    expected = MODEL_PROFILES[DEFAULT_MODEL_PROFILE]
    assert profile_for_model(expected.model_id, expected.revision) == expected
    assert profile_for_model(expected.model_id, "different") is None


def test_training_config_serializes_target_modules_for_manifests():
    config = TrainConfig(target_modules=("q_proj", "v_proj"))
    serialized = train_config_dict(config)
    assert serialized["target_modules"] == ["q_proj", "v_proj"]
