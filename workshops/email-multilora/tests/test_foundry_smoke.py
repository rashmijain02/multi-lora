import json
from unittest.mock import Mock

import pytest

pytest.importorskip("dotenv", reason="Install the cloud extra to test Foundry smoke checks.")

from email_workshop import foundry_smoke


@pytest.fixture
def smoke_env(tmp_path):
    path = tmp_path / ".env.foundry.proposal"
    path.write_text(
        "AZURE_SUBSCRIPTION_ID=test-subscription\n"
        "FOUNDRY_RESOURCE_GROUP=synthetic-group\n"
        "FOUNDRY_ACCOUNT_NAME=synthetic-foundry\n"
        "FOUNDRY_DEPLOYMENT_NAME=nemotron-email\n"
        "FOUNDRY_MODEL_ID=azureml://registries/azure-huggingface/models/"
        "synthetic-model/versions/2",
        encoding="utf-8",
    )
    return path


def deployed_resource(*, state="Succeeded", model=None):
    return json.dumps(
        {
            "properties": {
                "provisioningState": state,
                "model": model
                or "azureml://registries/azure-huggingface/models/synthetic-model/versions/2",
            }
        }
    )


def test_configuration_check_makes_no_azure_or_inference_calls(
    smoke_env, monkeypatch, capsys
):
    az = Mock(side_effect=AssertionError("No Azure calls permitted"))
    post = Mock(side_effect=AssertionError("No inference calls permitted"))
    monkeypatch.setattr(foundry_smoke, "az", az)
    monkeypatch.setattr(foundry_smoke.requests, "post", post)
    monkeypatch.setattr(
        "sys.argv", ["foundry_smoke", "--env-file", str(smoke_env)]
    )

    foundry_smoke.main()

    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "configuration check only; no Azure or inference calls"
    assert result["deployment"] == "nemotron-email"
    az.assert_not_called()
    post.assert_not_called()


def test_run_verifies_resource_and_performs_one_synthetic_inference(smoke_env, monkeypatch):
    az = Mock(side_effect=[deployed_resource(), "synthetic-entra-token"])
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "SMOKE_OK"},
                "finish_reason": "stop",
            }
        ]
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(foundry_smoke, "az", az)
    monkeypatch.setattr(foundry_smoke.requests, "post", post)

    result = foundry_smoke.run_smoke(foundry_smoke.smoke_config(smoke_env))

    assert result == {
        "status": "passed",
        "deployment": "nemotron-email",
        "provisioningState": "Succeeded",
        "inference": "valid chat-completions response",
        "finishReason": "stop",
        "outputField": "content",
        "completionTokens": "0",
        "data": "synthetic-only",
    }
    resource_call = az.call_args_list[0].args
    assert "--ids" in resource_call
    assert resource_call[resource_call.index("--ids") + 1].endswith(
        "/managedComputeDeployments/nemotron-email"
    )
    token_call = az.call_args_list[1].args
    assert token_call[:2] == ("account", "get-access-token")
    assert foundry_smoke.TOKEN_RESOURCE in token_call
    assert post.call_count == 1
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer synthetic-entra-token"
    assert "synthetic test data" in post.call_args.kwargs["json"]["messages"][0]["content"]
    assert post.call_args.kwargs["allow_redirects"] is False


def test_not_ready_deployment_stops_before_authentication(smoke_env, monkeypatch):
    az = Mock(return_value=deployed_resource(state="Creating"))
    post = Mock()
    monkeypatch.setattr(foundry_smoke, "az", az)
    monkeypatch.setattr(foundry_smoke.requests, "post", post)

    with pytest.raises(RuntimeError, match="not ready.*Creating"):
        foundry_smoke.run_smoke(foundry_smoke.smoke_config(smoke_env))

    assert az.call_count == 1
    post.assert_not_called()


def test_model_drift_stops_before_inference(smoke_env, monkeypatch):
    monkeypatch.setattr(
        foundry_smoke,
        "az",
        Mock(return_value=deployed_resource(model="azureml://registries/example/models/other/1")),
    )
    post = Mock()
    monkeypatch.setattr(foundry_smoke.requests, "post", post)

    with pytest.raises(RuntimeError, match="does not match"):
        foundry_smoke.run_smoke(foundry_smoke.smoke_config(smoke_env))

    post.assert_not_called()


def test_reasoning_only_response_proves_inference_health(smoke_env, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [
            {
                "message": {"content": "", "reasoning_content": "Synthetic reasoning"},
                "finish_reason": "length",
            }
        ]
    }
    monkeypatch.setattr(foundry_smoke.requests, "post", Mock(return_value=response))

    result = foundry_smoke.invoke_smoke(
        foundry_smoke.smoke_config(smoke_env), "synthetic-entra-token"
    )

    assert result == {
        "finishReason": "length",
        "outputField": "reasoning_content",
        "completionTokens": "0",
    }


def test_completion_usage_proves_reasoning_model_executed(smoke_env, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [
            {
                "message": {"role": "assistant", "content": None},
                "finish_reason": "length",
            }
        ],
        "usage": {"prompt_tokens": 16, "completion_tokens": 128, "total_tokens": 144},
    }
    monkeypatch.setattr(foundry_smoke.requests, "post", Mock(return_value=response))

    result = foundry_smoke.invoke_smoke(
        foundry_smoke.smoke_config(smoke_env), "synthetic-entra-token"
    )

    assert result == {
        "finishReason": "length",
        "outputField": "completion_token_usage",
        "completionTokens": "128",
    }


def test_verbose_diagnostics_show_schema_without_token_or_output(smoke_env, monkeypatch, capsys):
    response = Mock(status_code=200, headers={"Content-Type": "application/json"})
    response.json.return_value = {
        "choices": [
            {
                "message": {"content": "SENSITIVE_MODEL_OUTPUT"},
                "finish_reason": "stop",
            }
        ]
    }
    monkeypatch.setattr(foundry_smoke.requests, "post", Mock(return_value=response))

    result = foundry_smoke.invoke_smoke(
        foundry_smoke.smoke_config(smoke_env), "SENSITIVE_ACCESS_TOKEN", verbose=True
    )

    diagnostics = capsys.readouterr().err
    assert result == {
        "finishReason": "stop",
        "outputField": "content",
        "completionTokens": "0",
    }
    assert "Received inference response" in diagnostics
    assert '"httpStatus": 200' in diagnostics
    assert '"messageValueTypes"' in diagnostics
    assert "SENSITIVE_MODEL_OUTPUT" not in diagnostics
    assert "SENSITIVE_ACCESS_TOKEN" not in diagnostics


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": None}]}])
def test_invalid_chat_envelope_is_rejected(smoke_env, monkeypatch, payload):
    response = Mock(status_code=200)
    response.json.return_value = payload
    monkeypatch.setattr(foundry_smoke.requests, "post", Mock(return_value=response))

    with pytest.raises(RuntimeError, match="invalid chat-completions envelope"):
        foundry_smoke.invoke_smoke(
            foundry_smoke.smoke_config(smoke_env), "synthetic-entra-token"
        )


def test_placeholder_configuration_is_rejected_before_azure(smoke_env):
    content = smoke_env.read_text(encoding="utf-8").replace(
        "FOUNDRY_DEPLOYMENT_NAME=nemotron-email",
        "FOUNDRY_DEPLOYMENT_NAME=REPLACE_ME",
    )
    smoke_env.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="FOUNDRY_DEPLOYMENT_NAME"):
        foundry_smoke.smoke_config(smoke_env)
