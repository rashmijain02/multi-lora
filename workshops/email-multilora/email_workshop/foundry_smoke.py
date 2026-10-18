from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values

from email_workshop.cloud_deploy import ROOT, az

API_VERSION = "2026-07-15-preview"
TOKEN_RESOURCE = "https://cognitiveservices.azure.com"


def verbose_log(enabled: bool, message: str, details: object | None = None) -> None:
    if not enabled:
        return
    print(f"[foundry-smoke] {message}", file=sys.stderr)
    if details is not None:
        print(json.dumps(details, indent=2, sort_keys=True), file=sys.stderr)


def required_value(values: dict[str, str | None], name: str) -> str:
    value = (values.get(name) or "").strip()
    if not value or value.startswith("REPLACE_WITH_") or value == "REPLACE_ME":
        raise ValueError(f"Set {name} to a non-placeholder value in the smoke-test environment file.")
    return value


def smoke_config(env_file: Path) -> dict[str, str]:
    if not env_file.is_file():
        raise ValueError(f"Smoke-test environment file not found: {env_file}")
    values = dict(dotenv_values(env_file))
    config = {
        name: required_value(values, name)
        for name in (
            "AZURE_SUBSCRIPTION_ID",
            "FOUNDRY_RESOURCE_GROUP",
            "FOUNDRY_ACCOUNT_NAME",
            "FOUNDRY_DEPLOYMENT_NAME",
            "FOUNDRY_MODEL_ID",
        )
    }
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}[a-z0-9]", config["FOUNDRY_ACCOUNT_NAME"]):
        raise ValueError("FOUNDRY_ACCOUNT_NAME must be a 2-64 character lowercase DNS label.")
    if not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", config["FOUNDRY_DEPLOYMENT_NAME"]
    ):
        raise ValueError(
            "FOUNDRY_DEPLOYMENT_NAME must be 1-64 alphanumeric/dot/hyphen/underscore characters."
        )
    if not re.fullmatch(
        r"azureml://registries/azure-huggingface/models/[^/\s]+/versions/[^/\s]+",
        config["FOUNDRY_MODEL_ID"],
    ):
        raise ValueError("FOUNDRY_MODEL_ID must be a version-pinned azure-huggingface model URI.")
    return config


def model_resource_id(config: dict[str, str]) -> str:
    return (
        f"/subscriptions/{config['AZURE_SUBSCRIPTION_ID']}"
        f"/resourceGroups/{config['FOUNDRY_RESOURCE_GROUP']}"
        f"/providers/Microsoft.CognitiveServices/accounts/{config['FOUNDRY_ACCOUNT_NAME']}"
        f"/managedComputeDeployments/{config['FOUNDRY_DEPLOYMENT_NAME']}"
    )


def chat_completions_url(config: dict[str, str]) -> str:
    return (
        f"https://{config['FOUNDRY_ACCOUNT_NAME']}.services.ai.azure.com"
        "/openai/v1/chat/completions"
    )


def verify_control_plane(config: dict[str, str], *, verbose: bool = False) -> None:
    verbose_log(
        verbose,
        "Checking managed-compute control plane.",
        {"deployment": config["FOUNDRY_DEPLOYMENT_NAME"]},
    )
    resource = json.loads(
        az(
            "resource",
            "show",
            "--subscription",
            config["AZURE_SUBSCRIPTION_ID"],
            "--ids",
            model_resource_id(config),
            "--api-version",
            API_VERSION,
            "--output",
            "json",
        )
    )
    properties = resource.get("properties")
    if not isinstance(properties, dict):
        raise TypeError("Managed-compute deployment returned no properties.")
    state = properties.get("provisioningState")
    if state != "Succeeded":
        raise RuntimeError(f"Managed-compute deployment is not ready (state: {state or 'unknown'}).")
    deployed_model = properties.get("model")
    if deployed_model != config["FOUNDRY_MODEL_ID"]:
        raise RuntimeError("Managed-compute deployment model does not match FOUNDRY_MODEL_ID.")
    verbose_log(
        verbose,
        "Control-plane check passed.",
        {"modelMatchesProposal": True, "provisioningState": state},
    )


def azure_cli_access_token(config: dict[str, str], *, verbose: bool = False) -> str:
    verbose_log(verbose, "Requesting a Cognitive Services token from Azure CLI.")
    token = az(
        "account",
        "get-access-token",
        "--subscription",
        config["AZURE_SUBSCRIPTION_ID"],
        "--resource",
        TOKEN_RESOURCE,
        "--query",
        "accessToken",
        "--output",
        "tsv",
    )
    if not token:
        raise RuntimeError("Azure CLI returned an empty Cognitive Services access token.")
    verbose_log(verbose, "Azure CLI token acquired; token value is hidden.")
    return token


def response_schema(payload: object) -> dict[str, object]:
    summary: dict[str, object] = {"payloadType": type(payload).__name__}
    if not isinstance(payload, dict):
        return summary
    summary["topLevelKeys"] = sorted(str(key) for key in payload)
    choices = payload.get("choices")
    summary["choicesType"] = type(choices).__name__
    if not isinstance(choices, list):
        return summary
    summary["choicesCount"] = len(choices)
    if not choices:
        return summary
    choice = choices[0]
    summary["firstChoiceType"] = type(choice).__name__
    if not isinstance(choice, dict):
        return summary
    summary["firstChoiceKeys"] = sorted(str(key) for key in choice)
    summary["firstChoiceValueTypes"] = {
        str(key): type(value).__name__ for key, value in choice.items()
    }
    message = choice.get("message")
    if isinstance(message, dict):
        summary["messageKeys"] = sorted(str(key) for key in message)
        summary["messageValueTypes"] = {
            str(key): type(value).__name__ for key, value in message.items()
        }
    return summary


def invoke_smoke(
    config: dict[str, str], access_token: str, *, verbose: bool = False
) -> dict[str, str]:
    verbose_log(
        verbose,
        "Sending one synthetic chat-completions request.",
        {
            "deployment": config["FOUNDRY_DEPLOYMENT_NAME"],
            "endpoint": chat_completions_url(config),
            "maxTokens": 128,
        },
    )
    try:
        response = requests.post(
            chat_completions_url(config),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": config["FOUNDRY_DEPLOYMENT_NAME"],
                "messages": [
                    {
                        "role": "user",
                        "content": "Reply with SMOKE_OK. This request contains synthetic test data only.",
                    }
                ],
                "temperature": 0,
                "max_tokens": 128,
                "stream": False,
            },
            timeout=(10, 90),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise RuntimeError(
            "Foundry smoke transport failed; check connectivity and timeout."
        ) from None
    verbose_log(
        verbose,
        "Received inference response.",
        {
            "contentType": response.headers.get("Content-Type", "")
            if hasattr(response, "headers")
            else "",
            "httpStatus": response.status_code,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"Foundry smoke returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Foundry smoke returned HTTP 200 with a non-JSON body.") from None
    schema = response_schema(payload)
    verbose_log(verbose, "Sanitized response schema (values and model output hidden).", schema)
    try:
        choice = payload["choices"][0]
        if not isinstance(choice, dict):
            raise TypeError
        message = choice.get("message")
        finish_reason = choice.get("finish_reason") or "unknown"
        usage = payload.get("usage")
        completion_tokens = (
            usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
        )
        if isinstance(message, dict) and isinstance(message.get("content"), str) and message[
            "content"
        ].strip():
            output_field = "content"
        elif (
            isinstance(message, dict)
            and isinstance(message.get("reasoning_content"), str)
            and message["reasoning_content"].strip()
        ):
            output_field = "reasoning_content"
        elif isinstance(choice.get("text"), str) and choice["text"].strip():
            output_field = "text"
        elif (
            isinstance(completion_tokens, int)
            and completion_tokens > 0
            and finish_reason in {"stop", "length"}
        ):
            # Reasoning models can consume the small smoke-test output budget without
            # exposing a final content field. Token usage still proves model execution.
            output_field = "completion_token_usage"
        else:
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Foundry smoke returned an invalid chat-completions envelope.") from None
    result = {"finishReason": str(finish_reason), "outputField": output_field}
    if isinstance(completion_tokens, int):
        result["completionTokens"] = str(completion_tokens)
    return result


def run_smoke(config: dict[str, str], *, verbose: bool = False) -> dict[str, object]:
    verify_control_plane(config, verbose=verbose)
    inference = invoke_smoke(
        config,
        azure_cli_access_token(config, verbose=verbose),
        verbose=verbose,
    )
    verbose_log(verbose, "Deployment smoke test passed.")
    return {
        "status": "passed",
        "deployment": config["FOUNDRY_DEPLOYMENT_NAME"],
        "provisioningState": "Succeeded",
        "inference": "valid chat-completions response",
        **inference,
        "data": "synthetic-only",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify a Foundry managed-compute deployment with one synthetic inference."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env.foundry.proposal",
        help="Reviewed deployment proposal (defaults to .env.foundry.proposal).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Make one billable synthetic inference request after the control-plane check.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print credential-safe progress and response-schema diagnostics to stderr.",
    )
    args = parser.parse_args()
    config = smoke_config(args.env_file.resolve())
    verbose_log(
        args.verbose,
        "Configuration loaded.",
        {
            "deployment": config["FOUNDRY_DEPLOYMENT_NAME"],
            "environmentFile": str(args.env_file.resolve()),
        },
    )
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "configuration check only; no Azure or inference calls",
                    "deployment": config["FOUNDRY_DEPLOYMENT_NAME"],
                    "model": config["FOUNDRY_MODEL_ID"],
                    "warning": "Pass --run to make one synthetic inference request.",
                },
                indent=2,
            )
        )
        return
    print(json.dumps(run_smoke(config, verbose=args.verbose), indent=2))


if __name__ == "__main__":
    main()
