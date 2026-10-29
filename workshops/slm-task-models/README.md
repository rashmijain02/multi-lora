# Workshop 3: Small task models (SLMs) behind parity gates

Can a small model trained for one narrow job replace the hosted frontier model on that job, and
can we prove it before switching? This workshop answers that one PersonaDesk role at a time.

- **Built and measured:** the **router**. Given a persona and an email, it picks which of the six
  PersonaDesk policy checks apply.
- **Planned:** the judge and the controller's tool calling.

Read [PLAN.md](PLAN.md) first. It explains every concept, the Hermes integration, both hardware
tiers and the gate. The measured results, including the failures, are in
[docs/evidence/ROUTER_PARITY.md](docs/evidence/ROUTER_PARITY.md).

## Quick start (light tier, 10 GB NVIDIA GPU)

Run from `workshops/slm-task-models`. All path arguments are relative to this folder.

```bash
uv sync --group train
uv run python -m slm_router data             # synthetic train/val/test + 9 sealed gold fixtures
uv run python -m slm_router k0               # lexical baseline
for seed in 2026 2027 2028; do               # three independent training runs
  uv run --group train python -m slm_router train --seed $seed --out runs/router/student-s$seed
  uv run --group train python -m slm_router predict --model runs/router/student-s$seed
done
uv run python -m slm_router gate --baseline runs/router/k0 \
  --candidate runs/router/student-s2026 --candidate runs/router/student-s2027 \
  --candidate runs/router/student-s2028
```

On PowerShell, write the loop as `foreach ($seed in 2026,2027,2028) { ... }` and use
`$seed` in the paths.

Without a GPU you can still run `data`, `k0`, the gate on K0, and the tests:

```bash
uv sync
uv run pytest -q
uv run ruff check .
```

## Layout

| Path | What it is |
| --- | --- |
| `slm_router/labels.py` | Check space and persona ownership, mirrored from PersonaDesk (a test keeps them in sync) |
| `slm_router/synth.py` | Seeded synthetic teacher; held-out templates and names for test; versioned rounds |
| `slm_router/data.py` | Workshop-relative paths, JSONL, the sealed gold loader (PersonaDesk fixtures) |
| `slm_router/k0.py` | TF-IDF + logistic regression baseline |
| `slm_router/student.py` | Qwen2.5-0.5B-Instruct + LoRA student; strict JSON output parser |
| `slm_router/metrics.py` | Plain-Python metrics: exact match, per-check recall, invalid rate, noise false positives, latency |
| `slm_router/gate.py` | Hash-locked parity gate over several independent runs |
| `gates.json` | The gate thresholds (version 2) |
| `tests/test_router.py` | Focused tests; no GPU needed |
| `runs/` | Generated data, adapters and predictions (git-ignored) |
