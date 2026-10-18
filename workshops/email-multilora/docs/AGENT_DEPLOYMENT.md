# Agent runbook: managed Foundry email API

## Objective and boundary

Host the workshop API on Azure Container Apps and call an **existing**, compatible managed
Nemotron chat-completions endpoint. Do not train, upload adapters, provision a model, accept
marketplace terms, or reinterpret prompt domains as trained adapters.
Local LoRA notebooks/serving must remain unchanged.

## Inputs (never disclose values)

Read variable names/defaults from [the environment template](../.env.example).
The operator populates the ignored workshop `.env` locally. Never read or paste secret values
into chat or logs. Never stage `.env`, `.env.*` other than `.env.example`, datasets, or artifacts.
Environment values override `.env`; do not silently override an operator's environment.
Read [the developer guide](AZURE_DEPLOYMENT.md) before execution.

## Procedure and gates

1. Work from this workshop's root. Identify the intended Python executable explicitly.
2. Install with `python -m pip install -e ".[cloud,dev]"`. Restart existing notebook kernels.
3. Run `python -m email_workshop.cloud_deploy` (no cloud calls).
   Missing placeholders/consent are blockers, not permission to fabricate credentials.
4. Run mocked tests and lint listed in the developer guide. Compile both Bicep templates with
   `az bicep build --stdout`; never `build-params` with secrets loaded.
5. Verify `.env` is ignored with `git check-ignore .env` and that `.dockerignore` remains an
   allowlist. Do not run `git add -f` or bypass these exclusions.
6. Present the exact subscription ID, resource group, region, service list, external ingress,
   remote email boundary, cost categories, auth design, and validation gaps to the operator.
   Obtain explicit approval **before** `--apply`, resource creation, image build, or paid inference.
7. After approval, run `python -m email_workshop.cloud_deploy --apply`.
   It uses explicit subscription arguments; never change the CLI's global subscription.
8. Check the returned HTTPS `/healthz`. Run the authenticated **synthetic-only** smoke in the
   developer guide with separate approval for the model call. Confirm missing-token requests
   return 401 and valid requests return the documented response shape.
9. Report resources and endpoint, tests actually run, remaining limitations, costs and cleanup.
   Never claim live deployment or model verification if only local checks were performed.

## Stop conditions

- Missing consent, placeholders, non-HTTPS URL, incompatible API or auth, or lack of deployment approval.
- Missing RBAC, marketplace acceptance, model availability, region capacity, or subscription quota.
- Any request to send real emails without explicit data-processing approval.
- Unexpected existing infrastructure changes, leaked secrets, invalid upstream output, or a failed build.

Surface errors; no fake predictions, silent retries, local fallbacks, or swallowed deployment errors.
Investigate private portal diagnostics without pasting resolved parameters or raw upstream bodies.
Use the developer guide's known failure cases. Do not keep retrying paid calls.

## Definition of done

- Mocked tests and lint pass; template compilation status is reported accurately.
- Secrets remain ignored and absent from build context.
- Live work, **if approved**, has a responsive HTTPS API, protected classification and valid
  managed-model output; otherwise explicitly report “scaffolded, not deployed”.
- No local LoRA behavior changes and no claim that managed inference trains or serves those adapters.
