# Workshop Scripts

## Apple Silicon LoRA And Inference

Follow the [numbered Nemotron Mac lab](../docs/APPLE_SILICON_LORA.md) for the
training plan, prerequisites, data contract, and validation limits. Commands
below start in the workshop directory:

```sh
export MLX_PYTHON="$(brew --prefix vllm-metal)/libexec/bin/python"
"$MLX_PYTHON" scripts/check-nemotron-lora.py
sh scripts/train-nemotron.sh data/nemotron-mlx/finance artifacts/nemotron-mlx/finance-smoke --iters 2 --save-every 2
```

Prepare real train/validation JSONL first. The training script resolves relative
paths from the workshop root and rejects an existing output directory. Use a
reviewed local model snapshot via `--model` for reproducible experiments.

The separate `serve-nemotron.sh` starts base-model inference; `smoke-nemotron.py`
checks health and chat generation. LAN binding is opt-in with
`NEMOTRON_HOST=0.0.0.0`. This is unauthenticated HTTP for trusted networks only,
not proof of trained-adapter or multi-LoRA serving support.

## Foundry PowerShell Workflows

## Interactive managed-compute deployment wizard

Use `foundry_deployment_wizard.ps1` to choose a versioned model from the
`azure-huggingface` registry and create a local proposal:

```powershell
.\workshops\email-multilora\scripts\foundry_deployment_wizard.ps1 -EnvFile ..\..\.env
```

The wizard reuses the existing Foundry account and subscription/resource group from
the environment files; it does not create an account or resource group. It checks
sign-in and resource access, then lists model/version options using
`az ml model list --registry-name azure-huggingface`. If Azure CLI's `ml` extension
is missing, it asks before installing it. The first registry response contains model
names and a `latest version` field, not individual version records. The wizard applies
the regex to those names, lets you select a matching name, then queries and displays
the published versions for that exact name. It validates the selected version using
`az ml model show` and writes the fully qualified `FOUNDRY_MODEL_ID` into the ignored
local `.env.foundry.proposal` file.

The installed Azure ML extension exposes compatible references on `az ml model show`
and provides the preview `az ml deployment-template show` command. The wizard uses
the versioned default template to read authoritative `acceleratorMaps` metadata, then
uses the matching `/labels/latest` reference required by the managed-compute ARM API.
Versioned template references are rejected by that API. If those preview fields or
commands are unavailable for a model, the wizard falls back to an exact value from that
model's Foundry Deploy details. It does not invent compatible values.

The wizard never deploys just because it generated a proposal. Deployment requires
typing `DEPLOY`, then separately typing `APPROVED` to confirm terms, quota, capacity,
region and pricing. Managed GPU capacity can accrue charges while idle. Review the
proposal before authorizing anything. The wizard also does not set the Azure CLI's
default subscription or print account keys.

## Deployment status

From the workshop directory, list managed-compute deployments without changing Azure:

```powershell
.\scripts\foundry_status.ps1
```

The status script reports deployment name, provisioning state, SKU, capacity,
accelerator, and model. If no managed-compute resource exists, it also reports the
latest workshop ARM deployment state when available. It is a control-plane status check;
it does not invoke the model.

## Synthetic inference smoke test

After status reports `Succeeded`, validate the data plane with the Python smoke test.
From the workshop directory, first perform its local-only configuration check:

```powershell
.\.venv\Scripts\python.exe -m email_workshop.foundry_smoke
```

Then explicitly authorize one billable synthetic inference request:

```powershell
.\.venv\Scripts\python.exe -m email_workshop.foundry_smoke --run
```

For progress and response-shape diagnostics without printing the token or model output:

```powershell
.\.venv\Scripts\python.exe -m email_workshop.foundry_smoke --run --verbose
```

The smoke test reads the reviewed `.env.foundry.proposal`, confirms that the exact
managed-compute resource is in `Succeeded` state and still references the selected model,
obtains a Cognitive Services access token through the current Azure CLI login, and submits
one synthetic chat-completions request. It validates deployment availability and the response
envelope independently of the workshop's stricter classification JSON contract. It never reads
or prints an account key and never sends workshop or customer email. The signed-in identity
needs data-plane inference access. Use `--env-file` only to select a different reviewed
deployment proposal. Verbose mode reports each control-plane, authentication and inference
stage plus response field names and value types; credentials and response values remain hidden.
For reasoning models, consuming completion tokens with `finishReason` `stop` or `length` is
accepted as deployment-health evidence even when the small smoke budget produces no final
`content` field. That does not prove the workshop classification contract.

## Managed-compute teardown

Run teardown from the workshop directory as soon as the managed model is no longer
needed:

```powershell
.\scripts\foundry_teardown.ps1
```

The script defaults to the ignored `.env.foundry.proposal` generated by the deployment
wizard. Use `-EnvFile` only when intentionally targeting another reviewed proposal. It
shows the account and deployment name, then requires the exact confirmation
`DELETE <deployment-name>`. The Python helper rechecks that the account and deployment
exist, deletes only the `managedComputeDeployments` child resource, and waits until ARM
confirms it is gone. The Foundry account, project, resource group, and unrelated
deployments are preserved.

Deletion releases the accelerator allocation and stops future billing for that managed
compute deployment after Azure confirms deletion. It does not reverse charges already
incurred. Teardown is deliberately not automatic: do not schedule or invoke destructive
cleanup without an approved retention window and target review.

Options:

- `-EnvFile` selects the environment file to inherit settings from (defaults to the
  repository-root `.env`).
- `-ModelFilter` sets the default case-insensitive regex; the wizard prompts you
  to change it before listing models. It defaults to `nvidia`. For example,
  `nvidia.*nemotron` matches names containing both terms in that order; enter `*`
  at the prompt to list every registry model name. Invalid regex patterns are
  rejected and the wizard prompts again.

## Read-only probe launcher

`run_foundry_probe.ps1` is a single-line PowerShell launcher for the workshop's read-only Foundry probe.

It:

1. Finds Azure CLI, adding the standard Windows installation directory to this PowerShell process's `PATH` if needed. It does not modify the user or machine PATH.
2. Checks for an active Azure CLI sign-in and runs interactive `az login` only if necessary. It does not change the CLI's default subscription.
3. Runs the probe using the repository-root `.env` as the inherited environment source.
4. Generates or refreshes `workshops/email-multilora/.env.foundry.proposal` for review and copy/paste.

## Run

From the repository root:

```powershell
.\workshops\email-multilora\scripts\run_foundry_probe.ps1
```

Or from the workshop directory:

```powershell
.\scripts\run_foundry_probe.ps1
```

If PowerShell blocks the script under the current execution policy, use only the approved execution method for your device. For a session-scoped execution-policy adjustment where permitted:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\run_foundry_probe.ps1
```

The session scope does not persist after that PowerShell process exits. Do not change the machine-wide execution policy for this script.

The Python probe uses `uv` with the workshop `cloud` and `dev` extras when available, otherwise it uses `workshops/email-multilora/.venv/Scripts/python.exe`. Ensure one of those environments is available.

## Review the output

Open `workshops/email-multilora/.env.foundry.proposal`. The probe can inherit the subscription, resource group, region, account, and project from the repository `.env`. It leaves the version-pinned model URI, compatible deployment-template URI, and accelerator type as placeholders when they are not configured; obtain those from the model catalog/deployment wizard before deploying.

The proposal contains environment-specific Azure identifiers. It is ignored by Git, but treat its contents and the probe's JSON output as private; do not paste raw output into public issues, commits, or chat.

This launcher only probes Azure and creates/overwrites the local proposal file. It does not create or update Azure resources and does not deploy a model.
