# Managed Nemotron email workshop: developer setup and deployment

## Architecture and limits

Client → HTTPS Container Apps API → existing Foundry managed Nemotron deployment.
This is **managed-model multi-label inference**, not LoRA training or multi-adapter serving.
The existing CPU router, notebooks, PEFT training, and local vLLM paths are unchanged.
The cloud API reuses the workshop's ten-label prompt and strict output validator.
It returns `trained_adapter: false`; do not present its predictions as trained-adapter results.

Bring an existing Nemotron deployment with **chat completions**, API-key Bearer authentication,
`model`, `messages`, `temperature`, `max_tokens`, and standard non-streaming OpenAI response support.
Use its **Consume** page for the exact URL and deployment/model identifier. Availability, quota,
marketplace terms, region, and API support depend on your subscription and specific Nemotron variant.
This project does not provision Nemotron, accept marketplace terms, or assume that managed endpoints
can load the workshop's Qwen adapters. If your deployment has a different protocol, do not guess a
URL or silently substitute a model: adapt/test the client explicitly first.

If you do not have a model endpoint yet, use the separate
[Foundry model deployment guide](FOUNDRY_MODEL_DEPLOYMENT.md) and
[model agent runbook](FOUNDRY_MODEL_AGENT.md). That path provisions a dedicated Foundry
account/project and preview managed GPU deployment before you configure this API.
Its model compute can incur charges independently of Container Apps.

Reference: [Foundry v1 API and model support](https://learn.microsoft.com/azure/foundry/openai/api-version-lifecycle).
v1 URLs normally end in `/openai/v1/chat/completions` with no API version. Other compatible
deployments may need `FOUNDRY_API_VERSION`; it is sent as the `api-version` query parameter.
No streaming, structured-output extensions, tools, retries, or local-model fallback are assumed.

## Local setup (PowerShell)

Start in the `multi-lora` repository root. The following creates a workshop-local environment:

```powershell
Set-Location .\workshops\email-multilora
python -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -e '.[cloud,dev]'
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` locally; do not paste it into chat, issue trackers, or terminal transcripts.
An ignored placeholder-only `.env` is supplied in the working directory; it is not a tracked artifact.
Environment variables override `.env`. Deployment reads the workshop's `.env`; local API startup
reads `.env` in its working directory, so start it from this folder.

| Variable | Meaning |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | Explicit target subscription ID |
| `AZURE_RESOURCE_GROUP` | Dedicated workshop group; do not reuse a group holding unrelated resources |
| `AZURE_LOCATION` | Approved Container Apps/ACR location, not an assumed Nemotron availability region |
| `AZURE_CONTAINER_REGISTRY` | Globally unique lowercase alphanumeric name, 5–30 characters |
| `AZURE_CONTAINER_APP` | Lowercase app name, 2–32 characters, starts with a letter |
| `FOUNDRY_CHAT_COMPLETIONS_URL` | Exact HTTPS chat completions URL, without query/credentials |
| `FOUNDRY_MODEL` | Deployment identifier from Consume; not necessarily the catalog name |
| `FOUNDRY_API_KEY` | Endpoint-specific secret; no default, no checked-in key |
| `FOUNDRY_API_VERSION` | Empty for v1; otherwise the required inference API version |
| `ALLOW_REMOTE_EMAIL` | Must explicitly equal `true` after approving cloud processing |
| `WORKSHOP_API_TOKEN` | Unique random ASCII token, at least 32 characters, for calling the workshop API |

Generate a token with a password manager or Python `secrets.token_urlsafe(48)`, and save it only
in `.env`. The workshop token and Foundry key are different secrets. Never reuse either.
Use synthetic emails for smoke tests. Approve data residency, retention, model terms, and
organizational policy before allowing actual email content to leave the machine.

```powershell
& $python -m email_workshop.cloud_deploy
& $python -m uvicorn email_workshop.cloud_api:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

The first command validates configuration only; it makes **no Azure calls**. The API fails startup
on missing settings, placeholders, lack of consent, or a weak token. Test health in another terminal:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/healthz'
```

Health means the app/configuration started, **not** that the model is reachable. The authenticated
synthetic smoke below verifies model integration and incurs an inference charge.

## Provision and host

Install Azure CLI with a current Bicep CLI (supports `.bicepparam` and `readEnvironmentVariable`).
Run `az login` yourself. No agent should initiate login or provision paid resources without approval.
The target principal needs resource-group creation rights, resource deployment rights, ACR task/build
rights, and role assignment rights (for example Contributor plus Role Based Access Control
Administrator at the appropriate scope). A Reader-only identity cannot deploy.

Ensure `Microsoft.App`, `Microsoft.ContainerRegistry`, and `Microsoft.ManagedIdentity` resource
providers are registered in the target subscription. ACR build/task availability is subscription-specific.
Check region capacity and quota before applying. No live quota or pricing validation is implied by
the local configuration check.

```powershell
az bicep install
# Compile templates without provisioning; do not build-params (it could print resolved secrets).
az bicep build --file infra\registry.bicep --stdout > $null
az bicep build --file infra\main.bicep --stdout > $null
# Review subscription, group, region and resources in the configuration check output.
& $python -m email_workshop.cloud_deploy
# Only after explicit approval:
& $python -m email_workshop.cloud_deploy --apply
```

The deployment entry point:

1. Validates placeholders, explicit consent, endpoint shape, and API token locally.
2. Verifies the explicit subscription is accessible without changing your global CLI subscription.
3. Creates the dedicated resource group and Basic ACR with admin credentials disabled.
4. Builds a uniquely tagged image remotely through ACR Tasks. Local Docker is not required.
5. Deploys a managed Container Apps environment, user-assigned image-pull identity with scoped
   `AcrPull`, and one HTTPS-only app with 0.5 CPU/1 GiB, zero minimum and two maximum replicas.
6. Passes secrets through environment-resolved secure Bicep parameters to Container Apps secrets;
   no generated parameter file or command-line argument contains a key.
7. Prints the API URL, not credentials or raw Azure operation output.

The container context is allowlisted: only package sources, package manifest and Dockerfile are sent.
`.env`, datasets, notebooks, logs, artifacts, and Git history are excluded. The image runs as a
non-root user. Do not manually build/push a context that bypasses `.dockerignore`.

The API uses a workshop-scoped shared Bearer token. It is suitable for a controlled workshop,
not an unrestricted public multi-tenant service. Before production, add organizational identity,
per-user quotas/rate limiting, private networking as required, Key Vault-backed rotation,
durable audit/monitoring, supply-chain scanning and a reviewed network/data boundary.
External ingress is enabled, but unauthenticated classification requests return 401.
API docs are disabled; `/healthz` is public and contains no configuration details.
App access logs are disabled and application errors never include emails, upstream bodies, or keys.
Azure control-plane activity still follows your subscription's logging policy.

## Authenticated synthetic smoke

Save/run this Python snippet locally from the workshop directory; set the returned API URL first.
It reads credentials without printing them and submits synthetic text only.

```python
import os
import requests
from dotenv import load_dotenv

load_dotenv(".env", override=False)
url = "https://YOUR-APP-FQDN"
assert requests.get(f"{url}/healthz", timeout=60).status_code == 200
assert requests.post(
    f"{url}/classify", json={"subject": "Smoke", "body": "Synthetic only."}, timeout=60
).status_code == 401
response = requests.post(
    f"{url}/classify",
    headers={"Authorization": f"Bearer {os.environ['WORKSHOP_API_TOKEN']}"},
    json={"subject": "Flight confirmation", "body": "Your synthetic flight booking is confirmed."},
    timeout=120,
)
assert response.status_code == 200, f"Classification failed: HTTP {response.status_code}"
result = response.json()
assert result["backend"] == "foundry-managed" and result["trained_adapter"] is False
assert isinstance(result["labels"], list)
print(result)
```

Expected response shape:

```json
{"labels":["Travel & Bookings"],"backend":"foundry-managed","model":"YOUR-DEPLOYMENT","trained_adapter":false}
```

Labels depend on the actual model. An empty array is valid; malformed, duplicate, unknown,
truncated, or filtered output is a 502 error, never a fake successful classification.
Schema violations return 422, auth failures 401, local overload may return 503.

## Validation, updates, and troubleshooting

```powershell
& $python -m pytest tests\test_foundry.py tests\test_pipeline.py tests\test_paths.py -q
& $python -m ruff check email_workshop\foundry.py email_workshop\cloud_api.py email_workshop\cloud_deploy.py tests\test_foundry.py tests\test_paths.py
git check-ignore .env
```

Tests mock Foundry; they never submit email or incur charges. They cover consent, endpoint
validation, request/response contracts, token protection, schema bounds, sanitized failures,
and non-mutating deployment configuration checks.
The existing pipeline test also requires clean notebook outputs. If you have executed and saved
notebooks locally, its notebook-cleanliness check will fail until you intentionally clear those
outputs; deployment does not modify or clear your notebooks.

- **Startup fails:** fill placeholders and opt in; run from the workshop directory. A fresh root
  environment needs `pip install -e '.[cloud,dev]'`. Restart notebook kernels after editable installs.
- **401 from workshop:** check the client token; do not use the Foundry key as the API token.
- **502 / upstream 401 or 403:** verify the deployment's key-based Bearer authentication and access.
- **502 / upstream 404:** verify the full Consume URL and model/deployment name, including API protocol.
- **502 / 429:** inspect quota and concurrency; there are no automatic paid retries.
- **Invalid classification JSON:** check the actual model supports the declared contract; no markdown
  fences or extra prose are accepted. No fallback to local adapters is performed.
- **Image pull fails:** verify scoped `AcrPull`; role propagation may lag. Rerun after propagation.
- **Azure command fails:** the helper deliberately suppresses raw CLI output because it may echo
  resolved secrets. Inspect the named deployment or build in Azure Portal privately. Do not use
  `--debug` or publish parameter dumps. Do not compile resolved `.bicepparam` into a tracked JSON file.

Re-running `--apply` builds a new image tag and replaces the active revision. Resource names
remain stable; old ACR image tags remain and consume storage. Preserve a known-good image digest
for rollback and redeploy it with the same secure parameters. Rotate both keys in `.env` and
rerun deployment when needed; the active revision must pick up updated credentials.

## Costs and cleanup

Provisioning is opt-in; this scaffold does not create resources by itself. Costs include Basic
ACR storage, ACR Tasks builds, Container Apps consumption/cold starts and model inference
(or the existing model's reserved compute). Scaling to zero does not make the registry or
Foundry deployment free. Set Azure budgets and alerts before deploying; no price is guaranteed.

To remove only this workshop, verify the dedicated group name and subscription, then run:

```powershell
# Substitute reviewed IDs explicitly. This deletes ALL resources in that group.
az group delete --subscription YOUR-SUBSCRIPTION-ID --name YOUR-WORKSHOP-GROUP
```

The existing Foundry model is not removed unless you put it in that same group. Do not use a
shared production group. Keep `.env` out of backups intended for publication; revoke secrets
when retiring the workshop.
