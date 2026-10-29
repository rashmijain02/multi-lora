# Workshop 4: AutoResearch (light tier and DGX Spark tier)

A Hermes agent runs its own training experiments. Each time it:

1. edits `train.py`;
2. trains for a fixed few minutes;
3. gets graded by a harness it cannot change;
4. keeps or reverts the change.

It is based on Karpathy's [autoresearch](https://github.com/karpathy/autoresearch).

| Tier | Hardware | Budget per run | Status |
| --- | --- | --- | --- |
| Light | NVIDIA GPU with at least 10 GB, TinyStories data | 120 s | Measured on an RTX 3080 ([evidence](docs/evidence/LIGHT_TIER_BASELINE.md)) |
| Spark | NVIDIA DGX Spark (GB10) | 300 s | Plan only; verify on your Spark |

## Read in this order

1. [PLAN.md](PLAN.md): concepts, both tiers step by step, running the loop with Hermes,
   held-out testing, cost, capstones and troubleshooting.
2. [program.md](program.md): the agent's instructions. `init` fills in the placeholders.
3. [Light tier baseline evidence](docs/evidence/LIGHT_TIER_BASELINE.md): what a working setup
   looks like, with every number measured.

## What is in this folder

| Path | Purpose |
| --- | --- |
| `harness/autoresearch_harness.py` | `init`, `run`, `heldout` and `status`. Standard library only |
| `program.md` | Template for the agent's instructions |
| `tests/` | Harness tests (fake training script, no GPU needed) |
| `upstream/` | **Git-ignored.** Your clone of the training code and the dataset cache |
| `runs/` | **Git-ignored.** Per-tag `state.json`, `results.tsv`, run logs, `heldout.tsv` |

Run the tests from this directory:

```powershell
uv run --group dev pytest -q
uv run --group dev ruff check .
```
