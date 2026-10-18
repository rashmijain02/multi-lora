from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from email_workshop.cloud_deploy import ROOT, az
from email_workshop.foundry import required

API_VERSION = "2026-07-15-preview"
REPO_ROOT = ROOT.parents[1]


def optional(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "REPLACE_ME" in value:
        return ""
    return value


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


def load_foundry_env(env_file: Path | None = None) -> None:
    files = [REPO_ROOT / ".env", ROOT / ".env"]
    if env_file is not None:
        files.append(env_file)
    files.append(ROOT / ".env.foundry")
    seen: set[Path] = set()
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.exists():
            load_dotenv(path, override=False)


def model_config(env_file: Path | None = None) -> dict[str, str]:
    load_foundry_env(env_file)
    endpoint = optional("AZURE_AI_PROJECT_ENDPOINT")
    config = {
        "AZURE_SUBSCRIPTION_ID": required("AZURE_SUBSCRIPTION_ID"),
        "FOUNDRY_RESOURCE_GROUP": optional("FOUNDRY_RESOURCE_GROUP")
        or required("AZURE_RESOURCE_GROUP"),
        "FOUNDRY_LOCATION": optional("FOUNDRY_LOCATION") or required("AZURE_LOCATION"),
        "FOUNDRY_ACCOUNT_NAME": infer_account_name(
            endpoint, optional("FOUNDRY_ACCOUNT_NAME") or optional("AZURE_AI_ACCOUNT_NAME")
        ),
        "FOUNDRY_PROJECT_NAME": optional("FOUNDRY_PROJECT_NAME")
        or infer_project_name(endpoint, optional("AZURE_AI_PROJECT_NAME")),
        "FOUNDRY_DEPLOYMENT_NAME": required("FOUNDRY_DEPLOYMENT_NAME"),
        "FOUNDRY_MODEL_ID": required("FOUNDRY_MODEL_ID"),
        "FOUNDRY_DEPLOYMENT_TEMPLATE_ID": required("FOUNDRY_DEPLOYMENT_TEMPLATE_ID"),
        "FOUNDRY_ACCELERATOR_TYPE": required("FOUNDRY_ACCELERATOR_TYPE"),
    }
    if not config["FOUNDRY_ACCOUNT_NAME"]:
        raise ValueError(
            "Set FOUNDRY_ACCOUNT_NAME or provide AZURE_AI_ACCOUNT_NAME/AZURE_AI_PROJECT_ENDPOINT in .env."
        )
    if not config["FOUNDRY_PROJECT_NAME"]:
        raise ValueError(
            "Set FOUNDRY_PROJECT_NAME or provide AZURE_AI_PROJECT_NAME/AZURE_AI_PROJECT_ENDPOINT in .env."
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]", config["FOUNDRY_ACCOUNT_NAME"]):
        raise ValueError("FOUNDRY_ACCOUNT_NAME must be a 2-64 character lowercase DNS label.")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,63}", config["FOUNDRY_PROJECT_NAME"]):
        raise ValueError(
            "FOUNDRY_PROJECT_NAME must be 2-64 alphanumeric/dot/hyphen/underscore characters."
        )
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", config["FOUNDRY_DEPLOYMENT_NAME"]):
        raise ValueError(
            "FOUNDRY_DEPLOYMENT_NAME must be 1-64 alphanumeric/dot/hyphen/underscore characters."
        )
    if not re.fullmatch(
        r"azureml://registries/azure-huggingface/models/[^/\s]+/versions/[^/\s]+",
        config["FOUNDRY_MODEL_ID"],
    ):
        raise ValueError("FOUNDRY_MODEL_ID must be a version-pinned azure-huggingface model URI.")
    if not re.fullmatch(
        r"azureml://registries/azure-huggingface/deploymenttemplates/[^/\s]+/labels/latest",
        config["FOUNDRY_DEPLOYMENT_TEMPLATE_ID"],
    ):
        raise ValueError(
            "FOUNDRY_DEPLOYMENT_TEMPLATE_ID must be an azure-huggingface "
            "deployment-template URI ending in /labels/latest, as required by the managed-compute API."
        )
    capacity = os.environ.get("FOUNDRY_CAPACITY", "1").strip()
    if not capacity.isascii() or not capacity.isdigit() or int(capacity) < 1:
        raise ValueError("FOUNDRY_CAPACITY must be a positive integer number of model instances.")
    config["FOUNDRY_CAPACITY"] = capacity
    os.environ.update(config)
    return config


def model_resource_id(config: dict[str, str]) -> str:
    return (
        f"/subscriptions/{config['AZURE_SUBSCRIPTION_ID']}"
        f"/resourceGroups/{config['FOUNDRY_RESOURCE_GROUP']}"
        f"/providers/Microsoft.CognitiveServices/accounts/{config['FOUNDRY_ACCOUNT_NAME']}"
        f"/managedComputeDeployments/{config['FOUNDRY_DEPLOYMENT_NAME']}"
    )


def deploy_model(config: dict[str, str]) -> dict:
    if os.environ.get("FOUNDRY_DEPLOYMENT_APPROVED", "").lower() != "true":
        raise ValueError(
            "Set FOUNDRY_DEPLOYMENT_APPROVED=true after explicit cost/quota/terms approval."
        )
    subscription = config["AZURE_SUBSCRIPTION_ID"]
    group = config["FOUNDRY_RESOURCE_GROUP"]
    az(
        "cognitiveservices",
        "account",
        "show",
        "--subscription",
        subscription,
        "--resource-group",
        group,
        "--name",
        config["FOUNDRY_ACCOUNT_NAME"],
        "--output",
        "none",
    )
    outputs = json.loads(
        az(
            "deployment",
            "group",
            "create",
            "--subscription",
            subscription,
            "--resource-group",
            group,
            "--name",
            "email-workshop-foundry",
            "--parameters",
            str(Path("infra") / "foundry" / "main.bicepparam"),
            "--query",
            "properties.outputs",
            "--output",
            "json",
        )
    )
    state = az(
        "resource",
        "show",
        "--subscription",
        subscription,
        "--ids",
        model_resource_id(config),
        "--api-version",
        API_VERSION,
        "--query",
        "properties.provisioningState",
        "--output",
        "tsv",
    )
    if state != "Succeeded":
        raise RuntimeError(f"Managed compute deployment did not report Succeeded (state: {state}).")
    return outputs


def teardown_model(config: dict[str, str]) -> str:
    if os.environ.get("FOUNDRY_TEARDOWN_APPROVED", "").lower() != "true":
        raise ValueError(
            "Set FOUNDRY_TEARDOWN_APPROVED=true only after explicitly approving deletion."
        )
    subscription = config["AZURE_SUBSCRIPTION_ID"]
    group = config["FOUNDRY_RESOURCE_GROUP"]
    resource_id = model_resource_id(config)
    az(
        "cognitiveservices",
        "account",
        "show",
        "--subscription",
        subscription,
        "--resource-group",
        group,
        "--name",
        config["FOUNDRY_ACCOUNT_NAME"],
        "--output",
        "none",
    )
    az(
        "resource",
        "show",
        "--subscription",
        subscription,
        "--ids",
        resource_id,
        "--api-version",
        API_VERSION,
        "--output",
        "none",
    )
    az(
        "resource",
        "delete",
        "--subscription",
        subscription,
        "--ids",
        resource_id,
        "--api-version",
        API_VERSION,
    )
    az(
        "resource",
        "wait",
        "--deleted",
        "--subscription",
        subscription,
        "--ids",
        resource_id,
        "--api-version",
        API_VERSION,
        "--interval",
        "15",
        "--timeout",
        "1800",
    )
    return resource_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure or provision dedicated Foundry Nemotron compute."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional .env file to load before .env.foundry for inherited Azure/Foundry values.",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Provision billable managed GPU compute."
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete only the billable managed-compute deployment and wait for its removal.",
    )
    args = parser.parse_args()
    if args.apply and args.delete:
        parser.error("--apply and --delete are mutually exclusive.")
    config = model_config(args.env_file)
    if args.delete:
        teardown_model(config)
        print(
            f"Managed-compute deployment deleted and no longer present: "
            f"{config['FOUNDRY_DEPLOYMENT_NAME']}. "
            "The existing Foundry account and project were preserved."
        )
        return
    if not args.apply:
        print(
            json.dumps(
                {
                    **config,
                    "mode": "configuration check only; no Azure calls",
                    "sku": "GlobalManagedCompute",
                    "warning": "Preview; provisioned GPU capacity can accrue hourly charges while idle.",
                },
                indent=2,
            )
        )
        return
    outputs = deploy_model(config)
    print(json.dumps(outputs, indent=2))
    print(
        "Model provisioned. Follow docs/FOUNDRY_MODEL_DEPLOYMENT.md to obtain credentials privately "
        "and run an explicitly approved synthetic inference smoke."
    )


if __name__ == "__main__":
    main()
