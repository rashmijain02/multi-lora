# Agent runbook: dedicated Nemotron model deployment

Read [the model developer guide](FOUNDRY_MODEL_DEPLOYMENT.md) first. This runbook provisions
the model, not the [Container Apps API](AGENT_DEPLOYMENT.md).

1. Start in the repository root; navigate to `workshops/email-multilora`.
2. Reuse a valid Python environment and install `.[cloud,dev]` if needed.
3. The operator copies `infra/foundry/.env.example` to ignored `.env.foundry` and fills it
   locally. Never expose secret values or automatically copy keys into chat/tool arguments.
4. Confirm exact Nemotron model/version, compatible template/version, accelerator, preview
   eligibility, separate managed-compute quota, region capacity, license and price. Catalog
   examples are not proof of live availability. Do not substitute OpenAI TPM/VM quota checks.
5. Run `python -m email_workshop.foundry_deploy` for a no-cloud configuration check.
   Run `pytest tests/test_foundry_deploy.py tests/test_paths.py` and compile
   `infra/foundry/main.bicep` with `az bicep build --stdout`.
6. Present subscription, dedicated model group, region, account/project/deployment,
   model/template versions, accelerator/capacity, public/key-auth boundary and idle GPU costs.
   Get explicit provisioning approval; do not treat file generation as permission to deploy.
7. Only after the operator enables `FOUNDRY_DEPLOYMENT_APPROVED=true`, run
   `python -m email_workshop.foundry_deploy --apply`. Do not change global CLI subscription.
8. Confirm the model reports `Succeeded`. Report non-secret resource IDs, endpoint and
   deployment name. Never output `listKeys` or resolved secret-bearing parameter files.
9. Run `python -m email_workshop.foundry_smoke` for the no-cloud configuration check. After
   explicit inference approval, run it again with `--run`; it uses Azure CLI Entra authentication
   and sends synthetic text only. Report what actually ran. No live deployment/inference claim is
   permitted from mocked tests or Bicep compilation alone.
10. The operator privately fills the API's separate `.env` with endpoint/name/key. Follow the
    API deployment runbook separately; obtain permission before remote email/model calls.

Stop on missing approval, quota, preview enrollment, compatibility, licensing, permissions,
capacity, unexpected existing resources or private-network policy. Failures can leave paid
resources behind: inspect and report them, never delete a shared group or retry paid variants
automatically. The model and Container Apps have independent lifecycles and charges.
