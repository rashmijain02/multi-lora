# Workshop Validation Record

Validated on **2026-10-17** on Windows with Python 3.12.10 in the workshop's isolated environment.

## Executed

| Check | Result |
|---|---|
| Pinned live dataset download and schema validation | Passed: 2,105 source rows, ten multi-label categories |
| Duplicate-label audit | One conflicting text group; both rows quarantined; 2,103 retained |
| Leakage/integrity checks | No duplicate IDs within/across train, validation, test; content hashes checked |
| Iterative stratification, seed 2026 | 1,473 train / 312 validation / 318 test |
| CPU router and lexical baseline | Fit on train; thresholds selected on validation only |
| Actual Qwen tokenizer | All 1,473 training emails formatted for all four adapters: 5,892 examples checked |
| Completion masking | Prompt/padding ignored; full JSON target and EOS retained |
| Negative specialist examples | Operations 346; finance 1,239; travel 1,253; generalist 0 |
| Maximum observed training length | 254 tokens, within the configured 512-token limit |
| Automated tests | 22 passed, including real tiny-model LoRA optimizer steps |
| Adapter persistence | Four real tiny-model adapters saved, hash-verified, loaded on one base |
| Held-out smoke evaluation | All four LLM strategies exercised using the trained tiny test model |
| Serving client contract | Static command, model IDs, pretokenized payloads, concurrency, and errors checked with HTTP test doubles |
| Notebook validation | All three notebooks validated and executed with costly flags off; 48 cells total |
| Dependency compatibility | `pip check` passed |
| Source lint | Ruff passed |

The notebooks' executed copies and live-data manifests are saved locally under ignored `artifacts/notebook-validation/`. Unit tests use temporary synthetic data and a tiny random Qwen model; they neither download a full model nor submit a cloud job.

## CPU validation observations

These are **validation-set tuning diagnostics**, not final held-out test scores and not LoRA quality:

| Metric | Observed |
|---|---:|
| Lexical micro-F1 | 0.8044 |
| Lexical macro-F1 | 0.7838 |
| Lexical exact label-set match | 0.6026 |
| Validation-selected label threshold | 0.60 |
| Validation-selected routing threshold | 0.80 |
| Routing domain recall, aggregated | 0.9517 |
| Average selected specialist calls | 1.0321 |

The routing target applies to aggregate domain recall, not a separate 95% guarantee for finance or travel. Inspect `validation_recall_by_domain` in router metadata and the per-label final evaluation before accepting a threshold.

The CPU run used scikit-learn 1.9.1 and NumPy 2.5.4. Their versions are recorded in router metadata; rerun in a new experiment if versions or thresholds change.

## Not executed / not claimed

- Full Qwen2.5-0.5B adapter training on the real email dataset.
- Classification-quality gains from LoRA or multi-LoRA.
- GPU latency, peak VRAM, throughput, or production cost.
- A running vLLM GPU server or actual heterogeneous batch scheduling.
- Nemotron/NIM compatibility.
- Foundry/Azure deployment or external-adapter import support.
- Any cloud GPU job, Hub upload, or production email action.

The tiny training/evaluation tests prove pipeline behavior, not useful model predictions. Their random-model outputs must never be shown as enterprise-email quality.

## Warnings

The training smoke emits upstream Trackio/Gradio deprecation warnings. Notebook execution emits Windows Jupyter/ZeroMQ warnings. The pinned environments complete successfully; these warnings are not suppressed in the implementation. No workshop test failure remains.

## Reproduce

Follow [environment setup](README.md#environment-setup-windows--vs-code), then:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m ruff check email_workshop tests scripts
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe scripts\validate_notebooks.py --execute
```

For the full GPU quality experiment, use the explicit run gates and complete test protocol in [the workshop guide](README.md). Do not overwrite these validation diagnostics with smoke-model scores.

## Managed Foundry hosting scaffold (2026-10-17)

Validated separately with Python 3.12.10 in the recreated **workspace-root** environment,
with the `cloud,dev` extras installed:

| Check | Result |
|---|---|
| Managed inference and existing CPU pipeline tests | 46 passed with the existing notebook-cleanliness test deselected |
| Full targeted run before deselection | Notebook-cleanliness test failed because locally saved notebooks contain execution outputs; those outputs were left untouched |
| New cloud sources/tests lint | Ruff passed |
| Infrastructure compilation | Both Bicep templates compiled; `.bicepparam` compiled with synthetic values and discarded output |
| Real local API startup | Uvicorn started; health returned 200; unauthenticated classification returned 401; process stopped after validation |
| Dependency consistency | `pip check` passed |
| Secret exclusion | Workshop `.env` and environment-specific variants are ignored; `.env` is not tracked |
| Container image build | Not executed: Docker Linux engine is not running locally |
| Live deployment / Nemotron inference | Not executed; configuration remains placeholders, with remote processing disabled |

Cloud tests use HTTP test doubles; they do not prove model availability, API compatibility with a
particular Nemotron deployment, classification quality, or Azure resource readiness. No resources
were provisioned and no cloud model call was made. The upstream Starlette test client emits an
HTTPX deprecation warning. No live credentials were needed for these checks.

Follow [the Azure developer guide](docs/AZURE_DEPLOYMENT.md) and
[agent runbook](docs/AGENT_DEPLOYMENT.md) for configuration, explicit provisioning approval,
synthetic live smoke tests, costs, and cleanup.

## Repository-relative path portability (2026-10-17)

- Added repository-wide path instructions and a rule under `_agent/rules/`.
- Setup examples start at the repository root and navigate with relative paths.
- Azure subprocesses use relative template/build paths with an explicit workshop working directory.
- Notebook artifact overrides resolve relative to the workshop directory.
- vLLM adapter paths are relative to the Linux/WSL workshop directory; absolute paths and
  parent traversal are rejected.
- Cleared saved notebook outputs and execution counts, including machine-specific paths.
  Local artifact files were not changed.
- **55 tests passed**, including cloud, pipeline, notebook-cleanliness, and new portability checks.
  Ruff passed for the changed Python files. The earlier notebook-cleanliness failure is resolved.
- No live Azure deployment, GPU training, or model call was performed for this change.
