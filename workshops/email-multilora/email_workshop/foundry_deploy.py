from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from email_workshop.cloud_deploy import ROOT, az
from email_workshop.foundry import required

API_VERSION = "2026-07-15-preview"


def model_config() -> dict[str, str]:
    load_dotenv(ROOT / ".env.foundry", override=False)
    config = {
        name: required(name)
        for name in (
            "AZURE_SUBSCRIPTION_ID",
            "FOUNDRY_RESOURCE_GROUP",
            "FOUNDRY_LOCATION",
            "FOUNDRY_ACCOUNT_NAME",
            "FOUNDRY_PROJECT_NAME",
            "FOUNDRY_DEPLOYMENT_NAME",
            "FOUNDRY_MODEL_ID",
            "FOUNDRY_DEPLOYMENT_TEMPLATE_ID",
            "FOUNDRY_ACCELERATOR_TYPE",
        )
    }
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
    for key, collection in (
        ("FOUNDRY_MODEL_ID", "models"),
        ("FOUNDRY_DEPLOYMENT_TEMPLATE_ID", "deploymenttemplates"),
    ):
        if not re.fullmatch(
            rf"azureml://registries/azure-huggingface/{collection}/[^/\s]+/versions/[^/\s]+",
            config[key],
        ):
            raise ValueError(f"{key} must be a version-pinned azure-huggingface {collection} URI.")
    capacity = os.environ.get("FOUNDRY_CAPACITY", "1").strip()
    if not capacity.isascii() or not capacity.isdigit() or int(capacity) < 1:
        raise ValueError("FOUNDRY_CAPACITY must be a positive integer number of model instances.")
    config["FOUNDRY_CAPACITY"] = capacity
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
    az("account", "show", "--subscription", subscription, "--output", "none")
    az(
        "group",
        "create",
        "--subscription",
        subscription,
        "--name",
        group,
        "--location",
        config["FOUNDRY_LOCATION"],
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Configure or provision dedicated Foundry Nemotron compute."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Provision billable managed GPU compute."
    )
    args = parser.parse_args()
    config = model_config()
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
