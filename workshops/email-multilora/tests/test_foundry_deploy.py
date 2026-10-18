import json
from pathlib import Path
from unittest.mock import Mock

import pytest

pytest.importorskip("dotenv", reason="Install cloud dependencies for deployment tests.")

from email_workshop import foundry_deploy


@pytest.fixture
def config_env(monkeypatch):
    for name, value in {
        "AZURE_SUBSCRIPTION_ID": "synthetic-subscription",
        "FOUNDRY_RESOURCE_GROUP": "synthetic-model-group",
        "FOUNDRY_LOCATION": "synthetic-region",
        "FOUNDRY_ACCOUNT_NAME": "synthetic-foundry",
        "FOUNDRY_PROJECT_NAME": "workshop",
        "FOUNDRY_DEPLOYMENT_NAME": "nemotron-email",
        "FOUNDRY_MODEL_ID": "azureml://registries/azure-huggingface/models/synthetic-model/versions/2",
        "FOUNDRY_DEPLOYMENT_TEMPLATE_ID": (
            "azureml://registries/azure-huggingface/deploymenttemplates/synthetic-template/labels/latest"
        ),
        "FOUNDRY_ACCELERATOR_TYPE": "synthetic-accelerator",
        "FOUNDRY_CAPACITY": "1",
        "FOUNDRY_DEPLOYMENT_APPROVED": "false",
    }.items():
        monkeypatch.setenv(name, value)


def test_config_only_never_calls_azure(config_env, monkeypatch, capsys):
    run = Mock(side_effect=AssertionError("No cloud calls allowed"))
    monkeypatch.setattr(foundry_deploy, "az", run)
    monkeypatch.setattr("sys.argv", ["foundry_deploy"])
    foundry_deploy.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "configuration check only; no Azure calls"
    assert plan["sku"] == "GlobalManagedCompute"
    assert "hourly" in plan["warning"]
    run.assert_not_called()


def test_apply_requires_separate_approval(config_env, monkeypatch):
    run = Mock()
    monkeypatch.setattr(foundry_deploy, "az", run)
    with pytest.raises(ValueError, match="APPROVED"):
        foundry_deploy.deploy_model(foundry_deploy.model_config())
    run.assert_not_called()


@pytest.mark.parametrize("capacity", ["0", "-1", "1.5", "many", "", "１２"])
def test_capacity_validation(config_env, monkeypatch, capacity):
    monkeypatch.setenv("FOUNDRY_CAPACITY", capacity)
    with pytest.raises(ValueError, match="CAPACITY"):
        foundry_deploy.model_config()


@pytest.mark.parametrize(
    "name",
    [
        "FOUNDRY_MODEL_ID",
        "FOUNDRY_DEPLOYMENT_TEMPLATE_ID",
        "FOUNDRY_ACCELERATOR_TYPE",
    ],
)
def test_placeholder_rejected(config_env, monkeypatch, name):
    monkeypatch.setenv(name, "REPLACE_ME")
    with pytest.raises(ValueError, match=name):
        foundry_deploy.model_config()


def test_versioned_template_rejected_by_managed_compute_api_contract(config_env, monkeypatch):
    monkeypatch.setenv(
        "FOUNDRY_DEPLOYMENT_TEMPLATE_ID",
        "azureml://registries/azure-huggingface/deploymenttemplates/test/versions/3",
    )
    with pytest.raises(ValueError, match="labels/latest"):
        foundry_deploy.model_config()


def test_deploy_calls_use_relative_files_and_verify_state(config_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_DEPLOYMENT_APPROVED", "true")
    outputs = {
        "chatCompletionsUrl": {"value": "https://synthetic.example/openai/v1/chat/completions"}
    }
    run = Mock(side_effect=["", json.dumps(outputs), "Succeeded"])
    monkeypatch.setattr(foundry_deploy, "az", run)
    result = foundry_deploy.deploy_model(foundry_deploy.model_config())
    assert result == outputs
    args = run.call_args_list[1].args
    assert args[args.index("--parameters") + 1] == str(
        Path("infra") / "foundry" / "main.bicepparam"
    )
    calls = str(run.call_args_list)
    assert "listKeys" not in calls and "account', 'set" not in calls
    assert not any(call.args[:2] == ("group", "create") for call in run.call_args_list)
    assert "cognitiveservices', 'account', 'show" in calls
    assert "/managedComputeDeployments/nemotron-email" in calls
    assert "2026-07-15-preview" in calls


def test_nonterminal_model_state_is_not_success(config_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_DEPLOYMENT_APPROVED", "true")
    monkeypatch.setattr(foundry_deploy, "az", Mock(side_effect=["", "{}", "Failed"]))
    with pytest.raises(RuntimeError, match="did not report Succeeded"):
        foundry_deploy.deploy_model(foundry_deploy.model_config())


def test_arm_failure_propagates(config_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_DEPLOYMENT_APPROVED", "true")
    run = Mock(side_effect=["", RuntimeError("quota blocked")])
    monkeypatch.setattr(foundry_deploy, "az", run)
    with pytest.raises(RuntimeError, match="quota blocked"):
        foundry_deploy.deploy_model(foundry_deploy.model_config())
    assert run.call_count == 2


def test_teardown_requires_separate_approval(config_env, monkeypatch):
    run = Mock()
    monkeypatch.setattr(foundry_deploy, "az", run)
    with pytest.raises(ValueError, match="TEARDOWN_APPROVED"):
        foundry_deploy.teardown_model(foundry_deploy.model_config())
    run.assert_not_called()


def test_teardown_deletes_only_model_and_waits(config_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_TEARDOWN_APPROVED", "true")
    run = Mock(return_value="")
    monkeypatch.setattr(foundry_deploy, "az", run)

    resource_id = foundry_deploy.teardown_model(foundry_deploy.model_config())

    assert resource_id.endswith("/managedComputeDeployments/nemotron-email")
    calls = str(run.call_args_list)
    assert "resource', 'delete" in calls
    assert "resource', 'wait', '--deleted" in calls
    assert "2026-07-15-preview" in calls
    assert "group', 'delete" not in calls
    assert "cognitiveservices', 'account', 'delete" not in calls
    assert "projects" not in calls


def test_teardown_failure_propagates_before_delete(config_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_TEARDOWN_APPROVED", "true")
    run = Mock(side_effect=["", RuntimeError("deployment not found")])
    monkeypatch.setattr(foundry_deploy, "az", run)

    with pytest.raises(RuntimeError, match="deployment not found"):
        foundry_deploy.teardown_model(foundry_deploy.model_config())

    assert run.call_count == 2


def test_config_can_inherit_values_from_explicit_env_file(tmp_path, monkeypatch):
    repo_root = tmp_path / "multi-lora"
    workshop_root = repo_root / "workshops" / "email-multilora"
    workshop_root.mkdir(parents=True)
    custom_env = tmp_path / "custom.env"
    custom_env.write_text(
        "AZURE_SUBSCRIPTION_ID=test-subscription\n"
        "AZURE_RESOURCE_GROUP=synthetic-workshop-rg\n"
        "AZURE_LOCATION=synthetic-region\n"
        "AZURE_AI_PROJECT_NAME=synthetic-project\n"
        "AZURE_AI_PROJECT_ENDPOINT=https://synthetic-account.services.ai.azure.com/api/projects/synthetic-project",
        encoding="utf-8",
    )
    (workshop_root / ".env.foundry").write_text(
        "FOUNDRY_DEPLOYMENT_NAME=nemotron-email\n"
        "FOUNDRY_MODEL_ID=azureml://registries/azure-huggingface/models/synthetic-model/versions/2\n"
        "FOUNDRY_DEPLOYMENT_TEMPLATE_ID=azureml://registries/azure-huggingface/deploymenttemplates/synthetic-template/labels/latest\n"
        "FOUNDRY_ACCELERATOR_TYPE=synthetic-accelerator",
        encoding="utf-8",
    )
    monkeypatch.setattr(foundry_deploy, "ROOT", workshop_root)
    monkeypatch.setattr(foundry_deploy, "REPO_ROOT", repo_root)
    for name in list(foundry_deploy.os.environ):
        if name.startswith(("AZURE_", "FOUNDRY_")):
            monkeypatch.delenv(name, raising=False)

    config = foundry_deploy.model_config(custom_env)

    assert config["AZURE_SUBSCRIPTION_ID"] == "test-subscription"
    assert config["FOUNDRY_RESOURCE_GROUP"] == "synthetic-workshop-rg"
    assert config["FOUNDRY_LOCATION"] == "synthetic-region"
    assert config["FOUNDRY_ACCOUNT_NAME"] == "synthetic-account"
    assert config["FOUNDRY_PROJECT_NAME"] == "synthetic-project"
