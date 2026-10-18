import json
from pathlib import Path

import pytest

pytest.importorskip("dotenv", reason="Install cloud dependencies for Foundry probe tests.")

from email_workshop import foundry_probe


def test_probe_uses_repo_root_env_and_discovers_existing_foundry_assets(tmp_path, monkeypatch):
    repo_root = tmp_path / "multi-lora"
    workshop_root = repo_root / "workshops" / "email-multilora"
    workshop_root.mkdir(parents=True)
    (repo_root / ".env").write_text(
        "\n".join(
            [
                "AZURE_SUBSCRIPTION_ID=test-subscription",
                "AZURE_RESOURCE_GROUP=synthetic-workshop-rg",
                "AZURE_LOCATION=synthetic-region",
                "AZURE_AI_PROJECT_NAME=synthetic-project",
                "AZURE_AI_PROJECT_ENDPOINT=https://synthetic-account.services.ai.azure.com/api/projects/synthetic-project",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(foundry_probe, "ROOT", workshop_root)
    monkeypatch.setattr(foundry_probe, "REPO_ROOT", repo_root)
    for name in list(foundry_probe.os.environ):
        if name.startswith("AZURE_") or name.startswith("FOUNDRY_"):
            monkeypatch.delenv(name, raising=False)

    calls = []

    def run(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("account", "show"):
            return json.dumps({"id": "test-subscription", "name": "Test Sub", "tenantId": "tenant"})
        if args[:2] == ("provider", "show"):
            return "Registered"
        if args[:2] == ("group", "show"):
            return json.dumps({"name": "synthetic-workshop-rg", "location": "synthetic-region"})
        if args[:3] == ("cognitiveservices", "account", "list"):
            return json.dumps(
                [
                    {
                        "id": "/subscriptions/test-subscription/resourceGroups/synthetic-workshop-rg/providers/Microsoft.CognitiveServices/accounts/synthetic-account",
                        "name": "synthetic-account",
                        "kind": "AIServices",
                        "location": "synthetic-region",
                        "properties": {
                            "endpoint": "https://synthetic-account.services.ai.azure.com/",
                            "customSubDomainName": "synthetic-account",
                        },
                    }
                ]
            )
        if args[:3] == ("cognitiveservices", "account", "show"):
            return json.dumps(
                {
                    "id": "/subscriptions/test-subscription/resourceGroups/synthetic-workshop-rg/providers/Microsoft.CognitiveServices/accounts/synthetic-account",
                    "name": "synthetic-account",
                    "kind": "AIServices",
                    "location": "synthetic-region",
                    "properties": {
                        "endpoint": "https://synthetic-account.services.ai.azure.com/",
                        "customSubDomainName": "synthetic-account",
                        "publicNetworkAccess": "Enabled",
                        "disableLocalAuth": False,
                    },
                }
            )
        if args[:2] == ("rest", "--method") and any(
            "/projects?api-version=2025-06-01" in value for value in args
        ):
            return json.dumps(
                {
                    "value": [
                        {
                            "id": "/subscriptions/test-subscription/resourceGroups/synthetic-workshop-rg/providers/Microsoft.CognitiveServices/accounts/synthetic-account/projects/synthetic-project",
                            "name": "synthetic-project",
                            "location": "synthetic-region",
                        }
                    ]
                }
            )
        if args[:2] == ("rest", "--method") and any(
            "/managedComputeDeployments?api-version=2026-07-15-preview" in value
            for value in args
        ):
            return json.dumps(
                {
                    "value": [
                        {
                            "id": "/subscriptions/test-subscription/resourceGroups/synthetic-workshop-rg/providers/Microsoft.CognitiveServices/accounts/synthetic-account/managedComputeDeployments/existing-nemotron",
                            "name": "existing-nemotron",
                            "sku": {"name": "GlobalManagedCompute", "capacity": 1},
                            "properties": {
                                "provisioningState": "Succeeded",
                                "acceleratorType": "H100_80GB",
                                "model": "azureml://registries/azure-huggingface/models/nvidia--synthetic/versions/2",
                                "deploymentTemplate": "azureml://registries/azure-huggingface/deploymenttemplates/synthetic/versions/4",
                            },
                        }
                    ]
                }
            )
        raise AssertionError(args)

    monkeypatch.setattr(foundry_probe, "az", run)

    result = foundry_probe.probe_environment()

    assert result["loadedEnvFiles"] == [".env"]
    assert result["resolvedInputs"]["inferredTargetAccountName"] == "synthetic-account"
    assert result["resolvedInputs"]["inferredTargetProjectName"] == "synthetic-project"
    assert result["providerRegistration"]["registrationState"] == "Registered"
    assert result["recommendedEnvFoundry"]["FOUNDRY_RESOURCE_GROUP"] == "synthetic-workshop-rg-foundry"
    assert result["recommendedEnvFoundry"]["FOUNDRY_ACCOUNT_NAME"] == "synthetic-account"
    assert result["projects"][0]["name"] == "synthetic-project"
    assert result["managedComputeDeployments"][0]["name"] == "existing-nemotron"
    assert "FOUNDRY_MODEL_ID" in result["missingValues"]
    assert all(call[:2] != ("account", "set") for call in calls)


def test_probe_returns_partial_result_when_target_account_is_unknown(tmp_path, monkeypatch):
    repo_root = tmp_path / "multi-lora"
    workshop_root = repo_root / "workshops" / "email-multilora"
    workshop_root.mkdir(parents=True)
    (repo_root / ".env").write_text(
        "\n".join(
            [
                "AZURE_SUBSCRIPTION_ID=test-subscription",
                "AZURE_RESOURCE_GROUP=synthetic-workshop-rg",
                "AZURE_LOCATION=synthetic-region",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(foundry_probe, "ROOT", workshop_root)
    monkeypatch.setattr(foundry_probe, "REPO_ROOT", repo_root)
    for name in list(foundry_probe.os.environ):
        if name.startswith("AZURE_") or name.startswith("FOUNDRY_"):
            monkeypatch.delenv(name, raising=False)

    def run(*args: str) -> str:
        if args[:2] == ("account", "show"):
            return json.dumps({"id": "test-subscription"})
        if args[:2] == ("provider", "show"):
            return "Registered"
        if args[:2] == ("group", "show"):
            return json.dumps({"name": "synthetic-workshop-rg", "location": "synthetic-region"})
        if args[:3] == ("cognitiveservices", "account", "list"):
            return json.dumps([])
        raise AssertionError(args)

    monkeypatch.setattr(foundry_probe, "az", run)

    result = foundry_probe.probe_environment()

    assert result["candidateAccounts"] == []
    assert result["targetAccount"] is None
    assert result["projects"] == []
    assert result["managedComputeDeployments"] == []
    assert "FOUNDRY_ACCOUNT_NAME" in result["missingValues"]
