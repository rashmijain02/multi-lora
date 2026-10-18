from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from email_workshop.foundry import FoundryConfig, required

ROOT = Path(__file__).resolve().parents[1]


def deployment_config() -> dict[str, str]:
    load_dotenv(ROOT / ".env", override=False)
    FoundryConfig.from_env(load_env=False)
    config = {
        name: required(name)
        for name in (
            "AZURE_SUBSCRIPTION_ID",
            "AZURE_RESOURCE_GROUP",
            "AZURE_LOCATION",
            "AZURE_CONTAINER_REGISTRY",
            "AZURE_CONTAINER_APP",
        )
    }
    if not re.fullmatch(r"[a-z0-9]{5,30}", config["AZURE_CONTAINER_REGISTRY"]):
        raise ValueError("AZURE_CONTAINER_REGISTRY must be 5-30 lowercase letters/digits.")
    if (
        not re.fullmatch(r"[a-z][a-z0-9-]{0,30}[a-z0-9]", config["AZURE_CONTAINER_APP"])
        or "--" in config["AZURE_CONTAINER_APP"]
    ):
        raise ValueError(
            "AZURE_CONTAINER_APP must be 2-32 lowercase letters/digits/hyphens, "
            "start with a letter, end with a letter/digit and contain no consecutive hyphens."
        )
    token = required("WORKSHOP_API_TOKEN")
    if len(token) < 32 or not token.isascii():
        raise ValueError("WORKSHOP_API_TOKEN must contain at least 32 ASCII characters.")
    return config


def az(*args: str) -> str:
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is missing. Install Azure CLI and Bicep, then run az login.")
    result = subprocess.run(
        [executable, *args, "--only-show-errors"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        # Azure errors may echo resolved parameters. Never send raw stderr to logs.
        raise RuntimeError(
            f"Azure CLI operation {' '.join(args[:2])} failed (exit {result.returncode}). "
            "Inspect the Azure deployment/build operation in the portal; raw output was "
            "suppressed because it may contain credentials."
        )
    return result.stdout.strip()


def deploy(config: dict[str, str]) -> str:
    subscription = config["AZURE_SUBSCRIPTION_ID"]
    group = config["AZURE_RESOURCE_GROUP"]
    location = config["AZURE_LOCATION"]
    registry = config["AZURE_CONTAINER_REGISTRY"]
    common = ("--subscription", subscription, "--resource-group", group)
    az("account", "show", "--subscription", subscription, "--output", "none")
    az(
        "group",
        "create",
        "--subscription",
        subscription,
        "--name",
        group,
        "--location",
        location,
        "--output",
        "none",
    )
    server = az(
        "deployment",
        "group",
        "create",
        *common,
        "--name",
        "email-workshop-registry",
        "--template-file",
        str(Path("infra") / "registry.bicep"),
        "--parameters",
        f"registryName={registry}",
        f"location={location}",
        "--query",
        "properties.outputs.loginServer.value",
        "--output",
        "tsv",
    )
    tag = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    image = f"{server}/email-workshop:{tag}"
    az(
        "acr",
        "build",
        "--subscription",
        subscription,
        "--registry",
        registry,
        "--image",
        f"email-workshop:{tag}",
        "--file",
        "Dockerfile",
        ".",
        "--output",
        "none",
    )
    os.environ["WORKSHOP_CONTAINER_IMAGE"] = image
    return az(
        "deployment",
        "group",
        "create",
        *common,
        "--name",
        "email-workshop-api",
        "--parameters",
        str(Path("infra") / "main.bicepparam"),
        "--query",
        "properties.outputs.apiUrl.value",
        "--output",
        "tsv",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate config or deploy the managed email API.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create/update billable Azure resources and build the container.",
    )
    args = parser.parse_args()
    config = deployment_config()
    if not args.apply:
        print(
            json.dumps(
                {
                    **config,
                    "mode": "configuration check only; no Azure calls",
                    "resources": [
                        "Basic ACR",
                        "Container Apps environment",
                        "Container App",
                        "pull identity",
                    ],
                },
                indent=2,
            )
        )
        return
    print("Deploying approved configuration; Azure command output is not logged.")
    print(f"API URL: {deploy(config)}")
    print("Run the authenticated synthetic smoke test in docs/AZURE_DEPLOYMENT.md.")


if __name__ == "__main__":
    main()
