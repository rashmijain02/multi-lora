import json
from unittest.mock import Mock

import pytest
import requests

pytest.importorskip("fastapi", reason="Install the cloud extra to test managed hosting.")
pytest.importorskip("dotenv", reason="Install the cloud extra to test managed hosting.")

from fastapi.testclient import TestClient

from email_workshop.cloud_api import create_app
from email_workshop.cloud_deploy import deployment_config
from email_workshop.foundry import FoundryClassifier, FoundryConfig, FoundryError

URL = "https://example.services.ai.azure.com/openai/v1/chat/completions"
TOKEN = "test-only-token-not-a-real-secret-" * 2


@pytest.fixture
def cloud_env(monkeypatch):
    for name, value in {
        "FOUNDRY_CHAT_COMPLETIONS_URL": URL,
        "FOUNDRY_MODEL": "nemotron-test",
        "FOUNDRY_API_KEY": "synthetic-test-key",
        "ALLOW_REMOTE_EMAIL": "true",
        "WORKSHOP_API_TOKEN": TOKEN,
        "AZURE_SUBSCRIPTION_ID": "test-subscription",
        "AZURE_RESOURCE_GROUP": "test-resource-group",
        "AZURE_LOCATION": "eastus",
        "AZURE_CONTAINER_REGISTRY": "testregistry123",
        "AZURE_CONTAINER_APP": "test-email-api",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FOUNDRY_API_VERSION", "")


def upstream(monkeypatch, content='["Business", "Reminders"]', status=200, finish="stop"):
    response = Mock(status_code=status)
    response.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": finish}]
    }
    post = Mock(return_value=response)
    monkeypatch.setattr("email_workshop.foundry.requests.post", post)
    return post


def test_cloud_requires_explicit_consent(cloud_env, monkeypatch):
    monkeypatch.setenv("ALLOW_REMOTE_EMAIL", "false")
    with pytest.raises(ValueError, match="ALLOW_REMOTE_EMAIL"):
        FoundryConfig.from_env()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/chat/completions",
        "https://user:pass@example.com/chat/completions",
        "https://example.com/chat/completions?key=secret",
        "https://example.com/models",
    ],
)
def test_invalid_endpoint(url):
    with pytest.raises(ValueError):
        FoundryConfig(url, "model", "key")


def test_request_contract(cloud_env, monkeypatch):
    post = upstream(monkeypatch)
    backend = FoundryClassifier(FoundryConfig.from_env())
    assert backend.classify("Meeting", "Attend tomorrow.") == ["Business", "Reminders"]
    args, kwargs = post.call_args
    assert args == (URL,)
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-test-key"
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == (10, 90)
    assert kwargs["json"]["model"] == "nemotron-test"
    assert kwargs["json"]["messages"][-1]["role"] == "user"
    assert kwargs["params"] == {}
    assert "synthetic-test-key" not in repr(backend.config)


@pytest.mark.parametrize(
    "content", ['["unknown"]', '["Business","Business"]', "{}", "```json\n[]\n```"]
)
def test_invalid_labels_are_errors(cloud_env, monkeypatch, content):
    upstream(monkeypatch, content)
    with pytest.raises(FoundryError, match="invalid"):
        FoundryClassifier(FoundryConfig.from_env()).classify("s", "b")


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_errors_are_not_success(cloud_env, monkeypatch, status):
    upstream(monkeypatch, status=status)
    with pytest.raises(FoundryError, match=f"HTTP {status}"):
        FoundryClassifier(FoundryConfig.from_env()).classify("s", "b")


def test_timeout_is_sanitized(cloud_env, monkeypatch):
    monkeypatch.setattr(
        "email_workshop.foundry.requests.post",
        Mock(side_effect=requests.Timeout("sensitive payload")),
    )
    with pytest.raises(FoundryError) as error:
        FoundryClassifier(FoundryConfig.from_env()).classify("s", "b")
    assert "sensitive" not in str(error.value)


def test_truncated_output_rejected(cloud_env, monkeypatch):
    upstream(monkeypatch, "[]", finish="length")
    with pytest.raises(FoundryError):
        FoundryClassifier(FoundryConfig.from_env()).classify("s", "b")


@pytest.mark.parametrize("payload", [{"choices": [None]}, {"choices": []}, {"choices": ["bad"]}])
def test_malformed_response_shape(cloud_env, monkeypatch, payload):
    post = upstream(monkeypatch)
    post.return_value.json.return_value = payload
    with pytest.raises(FoundryError):
        FoundryClassifier(FoundryConfig.from_env()).classify("s", "b")


def test_protected_api_and_schema(cloud_env, monkeypatch):
    post = upstream(monkeypatch)
    with TestClient(create_app()) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/openapi.json").status_code == 404
        payload = {"subject": "Meeting", "body": "Attend tomorrow."}
        assert client.post("/classify", json=payload).status_code == 401
        assert (
            client.post(
                "/classify",
                json=payload,
                headers={
                    "Authorization": "Bearer wrong",
                },
            ).status_code
            == 401
        )
        post.assert_not_called()
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert (
            client.post("/classify", json={**payload, "body": " "}, headers=headers).status_code
            == 422
        )
        assert (
            client.post(
                "/classify", json={**payload, "body": "x" * 20001}, headers=headers
            ).status_code
            == 422
        )
        invalid = client.post("/classify", json={**payload, "private": "PRIVATE"}, headers=headers)
        assert invalid.status_code == 422
        assert "PRIVATE" not in invalid.text
        result = client.post("/classify", json=payload, headers=headers)
        assert result.status_code == 200
        assert result.json() == {
            "labels": ["Business", "Reminders"],
            "backend": "foundry-managed",
            "model": "nemotron-test",
            "trained_adapter": False,
        }


def test_api_upstream_failure_no_content_leak(cloud_env, monkeypatch, caplog):
    upstream(monkeypatch, status=500)
    with TestClient(create_app()) as client:
        result = client.post(
            "/classify",
            json={"subject": "PRIVATE", "body": "SECRET"},
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
    assert result.status_code == 502
    assert "PRIVATE" not in caplog.text + result.text
    assert "SECRET" not in caplog.text + result.text


def test_deployment_checks_placeholders(cloud_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_MODEL", "REPLACE_ME")
    with pytest.raises(ValueError, match="FOUNDRY_MODEL"):
        deployment_config()


def test_generated_placeholders_are_rejected(cloud_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_MODEL", "REPLACE_WITH_DEPLOYMENT_NAME")
    with pytest.raises(ValueError, match="FOUNDRY_MODEL"):
        FoundryConfig.from_env()


def test_deployment_rejects_invalid_app_name(cloud_env, monkeypatch):
    monkeypatch.setenv("AZURE_CONTAINER_APP", "email--workshop")
    with pytest.raises(ValueError, match="AZURE_CONTAINER_APP"):
        deployment_config()


def test_deployment_check_never_calls_azure(cloud_env, monkeypatch, capsys):
    from email_workshop import cloud_deploy

    run = Mock(side_effect=AssertionError("No Azure calls permitted"))
    monkeypatch.setattr(cloud_deploy.subprocess, "run", run)
    monkeypatch.setattr("sys.argv", ["cloud_deploy"])
    cloud_deploy.main()
    output = json.loads(capsys.readouterr().out)
    assert output["AZURE_RESOURCE_GROUP"] == "test-resource-group"
    assert "synthetic-test-key" not in json.dumps(output)
    run.assert_not_called()


def test_optional_api_version(cloud_env, monkeypatch):
    monkeypatch.setenv("FOUNDRY_API_VERSION", "2024-05-01-preview")
    post = upstream(monkeypatch)
    FoundryClassifier(FoundryConfig.from_env()).classify("s", "b")
    assert post.call_args.kwargs["params"] == {"api-version": "2024-05-01-preview"}


def test_deployment_passes_secrets_only_through_environment(cloud_env, monkeypatch):
    from email_workshop import cloud_deploy

    run = Mock(
        side_effect=[
            "",
            "",
            "testregistry123.azurecr.io",
            "",
            "https://test.azurecontainerapps.io",
        ]
    )
    monkeypatch.setattr(cloud_deploy, "az", run)
    assert cloud_deploy.deploy(deployment_config()) == "https://test.azurecontainerapps.io"
    calls = str(run.call_args_list)
    assert "synthetic-test-key" not in calls
    assert TOKEN not in calls
    assert "main.bicepparam" in calls
    assert "account', 'set" not in calls
    from pathlib import Path

    registry_call = run.call_args_list[2].args
    assert registry_call[registry_call.index("--template-file") + 1] == str(
        Path("infra") / "registry.bicep"
    )
    build_call = run.call_args_list[3].args
    assert build_call[build_call.index("--file") + 2] == "."
    deployment_call = run.call_args_list[4].args
    assert deployment_call[deployment_call.index("--parameters") + 1] == str(
        Path("infra") / "main.bicepparam"
    )
    import os

    assert os.environ["WORKSHOP_CONTAINER_IMAGE"].startswith(
        "testregistry123.azurecr.io/email-workshop:"
    )


def test_azure_failure_suppresses_secret_output(monkeypatch):
    from email_workshop import cloud_deploy

    monkeypatch.setattr(cloud_deploy.shutil, "which", Mock(return_value="az"))
    monkeypatch.setattr(
        cloud_deploy.subprocess,
        "run",
        Mock(
            return_value=Mock(
                returncode=1,
                stderr="synthetic-test-key",
                stdout="sensitive data",
            )
        ),
    )
    with pytest.raises(RuntimeError) as error:
        cloud_deploy.az("deployment", "group", "create")
    assert "synthetic-test-key" not in str(error.value)
    assert "sensitive data" not in str(error.value)
    assert "failed" in str(error.value)
