# Deploy Nemotron managed compute in Microsoft Foundry

This guide provisions the **model**, independently of
[the Container Apps API hosting deployment](AZURE_DEPLOYMENT.md).
Start here if you do not yet have `FOUNDRY_CHAT_COMPLETIONS_URL`.
For agents, use [the execution runbook](FOUNDRY_MODEL_AGENT.md).

## What is supported and what it takes

As documented on 2026-10-17, Foundry managed compute is **public preview**. Microsoft documents
`nvidia-nemotron-3-nano-30b-a3b-fp8` as an example using an H100-compatible deployment template.
This is evidence of a documented deployment path, **not** a guarantee that this model/template,
accelerator, region or preview is available to your subscription.

This scaffold uses `Microsoft.CognitiveServices/accounts/managedComputeDeployments`
with SKU `GlobalManagedCompute`, not the ordinary `accounts/deployments` token-based resource.
It creates a dedicated AIServices Foundry account, project, and model deployment in one group.
It does not provision Azure ML online endpoints, a NIM container on AKS, or Fireworks partner
deployments. Those are different hosting paths with different resource/API contracts.

You need:

1. An Azure subscription eligible for this preview and its paid managed compute offering.
   Visual Studio/free-credit subscriptions may have restrictions; verify eligibility rather
   than assuming credits or GPU quota are available.
2. A supported Foundry account region, approved **Foundry managed compute accelerator quota**
   and actual regional capacity. This quota is separate from VM GPU quota and token-based
   deployment quotas. Do not use Container Apps CPU quota or OpenAI TPM as a proxy.
3. A Nemotron model asset and compatible deployment-template version from the Foundry catalog,
   an accelerator type, and an instance count within approved quota.
4. Permissions to create the dedicated group/account/project and model. Microsoft lists
   Cognitive Services Contributor (or the applicable Foundry owner role) for managed compute
   control-plane operations. Account key retrieval needs `listKeys` permission.
5. A current Azure CLI/Bicep supporting the preview ARM API and `.bicepparam`. The template
   pins `2026-07-15-preview` for managed compute and `2025-06-01` for account/project.
6. Acceptance/review of the model license, any catalog or commercial terms, preview conditions,
   data processing and cost. The script does not accept terms or request quota for you.

**Costs:** treat this as provisioned GPU hosting, not free inference or an on-demand
per-token endpoint. Charges can accrue while capacity is provisioned even with no requests.
An instance may require multiple accelerators depending on its template. `capacity: 1` means
one model instance, not necessarily one GPU. Consult the selected offering's current pricing;
no monthly dollar estimate or automatic idle shutdown is provided. Container Apps scaling
to zero does **not** shut down this model deployment.

## 1. Select and pin a compatible catalog deployment

In Foundry, select the intended subscription/resource context, open the model catalog,
choose the Hugging Face collection, and locate the exact Nemotron variant.
Inspect the model card and its **Deploy** wizard without submitting a paid deployment.

Copy:

- The fully qualified **model ID**, including a version.
- A compatible **deployment template ID**, resolved to an explicit version.
- The accelerator type required by that template.

Microsoft's documented examples include a model URI shaped like:

```text
azureml://registries/azure-huggingface/models/nvidia--nvidia-nemotron-3-nano-30b-a3b-fp8/versions/2
```

The documented template example uses a mutable `/labels/latest` reference. This scaffold
intentionally requires `/versions/<version>` instead. Resolve the label to the actual
published template version via the catalog/registry before deployment. Do not invent a
version, assume the model version equals the template version, or substitute a random
OpenAI model/SKU when quota is unavailable. Accelerator values such as `H100_80GB` are
examples only; use what your selected template supports.

The model ID and template control weights/runtime/hardware; the **deployment name** is
the identifier the workshop will send as `FOUNDRY_MODEL`.

## 2. Prepare separate local configuration

Start at the `multi-lora` repository root:

```powershell
Set-Location .\workshops\email-multilora
python -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -e '.[cloud,dev]'
if (!(Test-Path .env.foundry)) { Copy-Item .\infra\foundry\.env.example .env.foundry }
```

If you already have the workshop environment, reuse it rather than recreating it.
Edit `.env.foundry` locally. It is ignored by the repository's `.env.*` rule.
Existing process environment variables take precedence; avoid mixing settings from another
subscription or environment in the same terminal.

If you already have a repository-root `.env` for the same subscription, you can probe the
current Azure environment before filling `.env.foundry`:

```powershell
python -m email_workshop.foundry_probe
```

The probe is read-only. It loads `workshops/email-multilora/.env.foundry`,
`workshops/email-multilora/.env` and the repository-root `.env` when present, then reports the
resolved subscription/resource-group/account/project context, existing AI Services accounts and
any managed-compute deployments it can see. It does **not** invent `FOUNDRY_MODEL_ID`,
`FOUNDRY_DEPLOYMENT_TEMPLATE_ID` or `FOUNDRY_ACCELERATOR_TYPE`; those still must come from the
Foundry catalog deploy wizard for the exact Nemotron variant you plan to use.

| Setting | Purpose |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | Explicit subscription; shared variable name with API hosting |
| `FOUNDRY_RESOURCE_GROUP` | Dedicated model group, preferably separate from the API group |
| `FOUNDRY_LOCATION` | Approved account/managed-compute region; independent of API region |
| `FOUNDRY_ACCOUNT_NAME` | Unique account name and custom DNS subdomain, 2-64 lowercase letters/digits/hyphens |
| `FOUNDRY_PROJECT_NAME` | New project under this account |
| `FOUNDRY_DEPLOYMENT_NAME` | Name used by inference requests |
| `FOUNDRY_MODEL_ID` | Version-pinned catalog model URI |
| `FOUNDRY_DEPLOYMENT_TEMPLATE_ID` | Compatible version-pinned runtime template URI |
| `FOUNDRY_ACCELERATOR_TYPE` | Accelerator supported by that template and your quota |
| `FOUNDRY_CAPACITY` | Positive integer instance count; starts at 1 |
| `FOUNDRY_DEPLOYMENT_APPROVED` | Keep false until explicit cost/quota/terms approval |

`.env.foundry` does not need the model key, workshop API token, Container Registry, or
`ALLOW_REMOTE_EMAIL`. It provisions resources, not classification requests.

```powershell
& $python -m email_workshop.foundry_deploy
git check-ignore .env.foundry
az bicep build --file infra\foundry\main.bicep --stdout > $null
```

The first command validates config locally and prints the non-secret deployment plan;
it makes no Azure calls and does not prove catalog compatibility, quota, permissions or
capacity. Template compilation checks syntax/schema, not service-side acceptance.
The installed Bicep 0.44.1 compiler emits `BCP081` for the new managed-compute preview
resource because its local type metadata is unavailable. Compilation still succeeds,
but those resource properties are not locally type-checked. They follow Microsoft's
published ARM reference; actual service acceptance remains a deployment-time check.

## 3. Review target and explicitly authorize deployment

Review subscription, group, account, project, region, exact model/template versions, accelerator,
capacity, public network access, key authentication, and pricing before authorizing `--apply`.
Set budgets and alerts. Confirm `Microsoft.CognitiveServices` is registered for the subscription.
Request managed compute quota through the Foundry capacity/quota experience if needed.

Run `az login` yourself, then set `FOUNDRY_DEPLOYMENT_APPROVED=true` in `.env.foundry` only
after approval. The helper also requires `--apply`:

```powershell
& $python -m email_workshop.foundry_deploy --apply
```

The helper checks access to the explicit subscription, creates the dedicated resource group,
and deploys [the model template](../infra/foundry/main.bicep) using
[environment-resolved parameters](../infra/foundry/main.bicepparam).
It waits for ARM deployment completion and then requires the model's
`provisioningState` to be `Succeeded`.

Outputs include resource IDs, the chat-completions URL and the deployment name.
**No account keys are retrieved, written, or output.** No inference request is made.
The deployment is publicly reachable with authentication and account keys enabled because
that matches the existing workshop client; it is not a private-network/Entra-only baseline.
System-assigned identities are created for the account/project, but no caller RBAC grants
or managed-identity inference authentication are configured.

Managed compute provisioning can take many minutes. If anything fails, resources already
created remain and may incur cost; there is no automatic rollback, quota request, model
substitution, region switch, or retry loop. Inspect the operation privately in Azure Portal.
The shared CLI wrapper suppresses raw error output to avoid credential disclosure.

## 4. Connect the model to the separate workshop API

In the existing workshop `.env`, set:

```dotenv
FOUNDRY_CHAT_COMPLETIONS_URL=https://YOUR-ACCOUNT.services.ai.azure.com/openai/v1/chat/completions
FOUNDRY_MODEL=YOUR-DEPLOYMENT-NAME
FOUNDRY_API_VERSION=
ALLOW_REMOTE_EMAIL=false
```

Use the output URL and deployment name, **not** the project URL or registry model URI.
In the account's Keys and Endpoint settings, privately obtain an account API key and save
it as `FOUNDRY_API_KEY` in `.env`. Do not paste keys into chat, print them in command output,
include them in Bicep outputs, or commit them. If policy prohibits key access/public endpoints,
stop: the existing app must be extended for Entra identity/private networking before use.

The inference scope is the Foundry account; managed compute documentation describes v1
chat completions with either API-key or Entra authentication. The current workshop uses
the API-key Bearer path. Catalog/preview behavior must still be verified live.

After approving remote processing, set `ALLOW_REMOTE_EMAIL=true` and follow
[the API hosting guide](AZURE_DEPLOYMENT.md) to deploy Container Apps. That command does
not create/recreate the model; this model deployment command does not deploy Container Apps.
Both use separate settings/files and can be updated independently.

Run the developer guide's authenticated **synthetic-only** smoke with explicit inference approval.
Verify `/healthz`, 401 without the workshop token, and a valid `/classify` response.
Health alone does not verify the model. Nemotron reasoning/context/output behavior varies by
variant/template; the app's strict JSON contract and 256-output-token limit must work for
your selection. If it returns filtered/truncated/non-JSON content, the API returns 502;
do not claim useful classification quality until evaluated.

## 5. Operations, safety and cleanup

- The model/runtime are version-pinned and auto-upgrades disabled. Plan deliberate upgrades
  before versions expire. Immutable model or accelerator changes may require a new deployment
  name; do not assume rerunning Bicep can change them in place.
- No built-in managed compute content filtering is promised in preview. If policy requires
  filtering, add an explicit reviewed content-safety layer before sending real emails.
- `GlobalManagedCompute` must not be treated as a promise of region-bound inference residency.
  Verify the offering's current processing/data-location terms before selecting it.
- No automatic scale-to-zero, stop schedule, production monitoring, model benchmark,
  LoRA training, or adapter import is configured.
- To remove paid GPU capacity, delete the managed compute deployment in the portal or
  remove the dedicated model group after checking its contents. Stopping/deleting only the
  Container App does not stop model billing.

For a deliberately dedicated disposable group only:

```powershell
# Replace with reviewed target values; this deletes EVERY resource in the model group.
az group delete --subscription YOUR-SUBSCRIPTION-ID --name YOUR-FOUNDRY-MODEL-GROUP
```

If deployment fails, first check preview eligibility, managed-compute quota, region capacity,
model/template compatibility, permissions, and name availability. Do not repeatedly submit
billable alternatives or accept new terms automatically.

## Official references and verification boundary

- [Managed compute deployment walkthrough](https://learn.microsoft.com/azure/foundry/how-to/deploy-models-managed)
- [Managed compute overview](https://learn.microsoft.com/azure/foundry/concepts/managed-compute-overview)
- [Managed compute Bicep resource](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/accounts/managedcomputedeployments)
- [Foundry project Bicep resource](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects)

This repository provides a scaffold and local validation, not a guarantee of deployment
availability for an arbitrary Nemotron model. No live model deployment or inference is
implied by template compilation or mocked tests.

Local validation on 2026-10-17: 70 tests passed, one optional training module skipped,
Ruff passed, and the model template/parameter wiring compiled with synthetic values.
No paid resources were created, quota/capacity verified, model terms accepted, or inference
requests sent. The `BCP081` warning above remains visible, not suppressed.
