from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from email_workshop.cloud_deploy import ROOT, az

ACCOUNT_API_VERSION = "2025-06-01"
MANAGED_COMPUTE_API_VERSION = "2026-07-15-preview"
REPO_ROOT = ROOT.parents[1]


def optional(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "REPLACE_ME" in value:
        return ""
    return value


def repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def load_probe_env() -> list[str]:
    loaded: list[str] = []
    for path in (ROOT / ".env.foundry", ROOT / ".env", REPO_ROOT / ".env"):
        if path.exists():
            load_dotenv(path, override=False)
            loaded.append(repo_relative(path))
    return loaded


def infer_account_name(endpoint: str, explicit_name: str) -> str:
    if explicit_name:
        return explicit_name
    if not endpoint:
        return ""
    parsed = urlsplit(endpoint)
    hostname = (parsed.hostname or "").lower()
    if hostname.endswith(".services.ai.azure.com"):
        return hostname.split(".", 1)[0]
    return ""


def infer_project_name(endpoint: str, explicit_name: str) -> str:
    if explicit_name:
        return explicit_name
    if not endpoint:
        return ""
    parts = [part for part in urlsplit(endpoint).path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "projects":
        return parts[2]
    return ""


def suggested_foundry_group(group: str) -> str:
    if not group:
        return ""
    return group if group.endswith("-foundry") else f"{group}-foundry"


def _json_or_error(*args: str) -> tuple[dict | list | None, str | None]:
    try:
        return json.loads(az(*args, "--output", "json")), None
    except RuntimeError as exc:
        return None, str(exc)


def _tsv_or_error(*args: str) -> tuple[str | None, str | None]:
    try:
        return az(*args, "--output", "tsv"), None
    except RuntimeError as exc:
        return None, str(exc)


def _list_accounts(subscription: str, group: str) -> tuple[list[dict], str | None]:
    args = ["cognitiveservices", "account", "list", "--subscription", subscription]
    if group:
        args.extend(("--resource-group", group))
    payload, error = _json_or_error(*args)
    if payload is None:
        return [], error
    assert isinstance(payload, list)
    accounts = []
    for item in payload:
        properties = item.get("properties") or {}
        accounts.append(
            {
                "name": item.get("name", ""),
                "kind": item.get("kind", ""),
                "location": item.get("location", ""),
                "id": item.get("id", ""),
                "endpoint": properties.get("endpoint", ""),
                "customSubDomainName": properties.get("customSubDomainName", ""),
            }
        )
    return accounts, None


def _show_account(subscription: str, group: str, account_name: str) -> tuple[dict | None, str | None]:
    payload, error = _json_or_error(
        "cognitiveservices",
        "account",
        "show",
        "--subscription",
        subscription,
        "--resource-group",
        group,
        "--name",
        account_name,
    )
    if payload is None:
        return None, error
    assert isinstance(payload, dict)
    properties = payload.get("properties") or {}
    return (
        {
            "name": payload.get("name", ""),
            "kind": payload.get("kind", ""),
            "location": payload.get("location", ""),
            "id": payload.get("id", ""),
            "endpoint": properties.get("endpoint", ""),
            "customSubDomainName": properties.get("customSubDomainName", ""),
            "publicNetworkAccess": properties.get("publicNetworkAccess", ""),
            "disableLocalAuth": properties.get("disableLocalAuth"),
        },
        None,
    )


def _arm_list(resource_id: str, api_version: str) -> tuple[list[dict], str | None]:
    payload, error = _json_or_error(
        "rest",
        "--method",
        "get",
        "--uri",
        f"https://management.azure.com{resource_id}?api-version={api_version}",
    )
    if payload is None:
        return [], error
    assert isinstance(payload, dict)
    value = payload.get("value")
    if not isinstance(value, list):
        return [], None
    return value, None


def probe_environment() -> dict:
    loaded_env_files = load_probe_env()
    subscription = optional("AZURE_SUBSCRIPTION_ID")
    group = optional("FOUNDRY_RESOURCE_GROUP") or optional("AZURE_RESOURCE_GROUP")
    location = optional("FOUNDRY_LOCATION") or optional("AZURE_LOCATION")
    explicit_account = optional("FOUNDRY_ACCOUNT_NAME") or optional("AZURE_AI_ACCOUNT_NAME")
    endpoint = optional("AZURE_AI_PROJECT_ENDPOINT")
    project_name = optional("FOUNDRY_PROJECT_NAME") or infer_project_name(
        endpoint, optional("AZURE_AI_PROJECT_NAME")
    )
    account_name = infer_account_name(endpoint, explicit_account)

    result = {
        "loadedEnvFiles": loaded_env_files,
        "resolvedInputs": {
            "AZURE_SUBSCRIPTION_ID": subscription,
            "AZURE_RESOURCE_GROUP": optional("AZURE_RESOURCE_GROUP"),
            "AZURE_LOCATION": optional("AZURE_LOCATION"),
            "AZURE_AI_PROJECT_NAME": optional("AZURE_AI_PROJECT_NAME"),
            "AZURE_AI_PROJECT_ENDPOINT": endpoint,
            "inferredTargetResourceGroup": group,
            "inferredTargetLocation": location,
            "inferredTargetAccountName": account_name,
            "inferredTargetProjectName": project_name,
        },
        "subscription": None,
        "providerRegistration": None,
        "resourceGroup": None,
        "candidateAccounts": [],
        "targetAccount": None,
        "projects": [],
        "managedComputeDeployments": [],
        "recommendedEnvFoundry": {
            "AZURE_SUBSCRIPTION_ID": subscription,
            "FOUNDRY_RESOURCE_GROUP": optional("FOUNDRY_RESOURCE_GROUP") or suggested_foundry_group(group),
            "FOUNDRY_LOCATION": optional("FOUNDRY_LOCATION") or location,
            "FOUNDRY_ACCOUNT_NAME": optional("FOUNDRY_ACCOUNT_NAME") or account_name,
            "FOUNDRY_PROJECT_NAME": optional("FOUNDRY_PROJECT_NAME") or project_name,
            "FOUNDRY_DEPLOYMENT_NAME": optional("FOUNDRY_DEPLOYMENT_NAME") or "nemotron-email",
            "FOUNDRY_MODEL_ID": optional("FOUNDRY_MODEL_ID"),
            "FOUNDRY_DEPLOYMENT_TEMPLATE_ID": optional("FOUNDRY_DEPLOYMENT_TEMPLATE_ID"),
            "FOUNDRY_ACCELERATOR_TYPE": optional("FOUNDRY_ACCELERATOR_TYPE"),
            "FOUNDRY_CAPACITY": optional("FOUNDRY_CAPACITY") or "1",
        },
        "missingValues": [],
        "notes": [
            "This probe is read-only and never changes the Azure CLI default subscription.",
            "Model ID, deployment template ID, and accelerator type must still come from the Foundry catalog deploy wizard.",
        ],
    }

    if not subscription:
        result["missingValues"] = [
            "AZURE_SUBSCRIPTION_ID",
            "FOUNDRY_MODEL_ID",
            "FOUNDRY_DEPLOYMENT_TEMPLATE_ID",
            "FOUNDRY_ACCELERATOR_TYPE",
        ]
        result["notes"].append(
            "Set AZURE_SUBSCRIPTION_ID in workshops/email-multilora/.env or the repository root .env before probing Azure."
        )
        return result

    payload, error = _json_or_error("account", "show", "--subscription", subscription)
    result["subscription"] = payload if error is None else {"id": subscription, "error": error}

    registration, error = _tsv_or_error(
        "provider",
        "show",
        "--subscription",
        subscription,
        "--namespace",
        "Microsoft.CognitiveServices",
        "--query",
        "registrationState",
    )
    result["providerRegistration"] = (
        {"namespace": "Microsoft.CognitiveServices", "registrationState": registration}
        if error is None
        else {"namespace": "Microsoft.CognitiveServices", "error": error}
    )

    if group:
        payload, error = _json_or_error(
            "group", "show", "--subscription", subscription, "--name", group
        )
        result["resourceGroup"] = payload if error is None else {"name": group, "error": error}

    accounts, error = _list_accounts(subscription, group)
    result["candidateAccounts"] = accounts
    if error is not None:
        result["candidateAccountsError"] = error

    if not account_name and len(accounts) == 1:
        account_name = accounts[0]["name"]
        result["resolvedInputs"]["inferredTargetAccountName"] = account_name
        result["recommendedEnvFoundry"]["FOUNDRY_ACCOUNT_NAME"] = account_name

    target_account_id = ""
    if account_name and group:
        account, error = _show_account(subscription, group, account_name)
        result["targetAccount"] = account if error is None else {"name": account_name, "error": error}
        if account:
            target_account_id = account["id"]
            if not result["recommendedEnvFoundry"]["FOUNDRY_LOCATION"]:
                result["recommendedEnvFoundry"]["FOUNDRY_LOCATION"] = account["location"]

    if target_account_id:
        projects, error = _arm_list(f"{target_account_id}/projects", ACCOUNT_API_VERSION)
        if error is None:
            result["projects"] = [
                {
                    "name": item.get("name", ""),
                    "id": item.get("id", ""),
                    "location": item.get("location", ""),
                }
                for item in projects
            ]
        else:
            result["projectsError"] = error

        deployments, error = _arm_list(
            f"{target_account_id}/managedComputeDeployments", MANAGED_COMPUTE_API_VERSION
        )
        if error is None:
            result["managedComputeDeployments"] = [
                {
                    "name": item.get("name", ""),
                    "id": item.get("id", ""),
                    "sku": (item.get("sku") or {}).get("name", ""),
                    "capacity": (item.get("sku") or {}).get("capacity"),
                    "provisioningState": (item.get("properties") or {}).get(
                        "provisioningState", ""
                    ),
                    "acceleratorType": (item.get("properties") or {}).get(
                        "acceleratorType", ""
                    ),
                    "model": (item.get("properties") or {}).get("model", ""),
                    "deploymentTemplate": (item.get("properties") or {}).get(
                        "deploymentTemplate", ""
                    ),
                }
                for item in deployments
            ]
        else:
            result["managedComputeDeploymentsError"] = error

    missing = []
    for name, value in result["recommendedEnvFoundry"].items():
        if name in {
            "FOUNDRY_MODEL_ID",
            "FOUNDRY_DEPLOYMENT_TEMPLATE_ID",
            "FOUNDRY_ACCELERATOR_TYPE",
        }:
            if not value:
                missing.append(name)
            continue
        if not value:
            missing.append(name)
    result["missingValues"] = missing
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only probe for the workshop's target Azure Foundry environment."
    )
    parser.parse_args()
    print(json.dumps(probe_environment(), indent=2))


if __name__ == "__main__":
    main()