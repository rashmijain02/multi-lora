"""Parity gate: is a router candidate good enough to replace the hosted controller's choice?

The thresholds live in ``gates.json``. Their sha256 is pinned below, so loosening a threshold
after seeing results is a visible code change, not a quiet edit (the same "locked metric" idea
as Workshop 4's harness). The candidate never grades itself: this module only reads labels the
candidate did not produce.
"""

from __future__ import annotations

import json
from pathlib import Path

from slm_router.metrics import score

GATES_SHA256 = "b38bb74d138a70a3a8f17f6619357c0979f26b21e3ece09f37a30b25c3b84043"


def load_gates(path: Path, expected_sha256: str = GATES_SHA256) -> dict:
    import hashlib

    # Normalise line endings so a Windows checkout (CRLF) hashes the same as Linux (LF).
    digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if digest != expected_sha256:
        raise SystemExit(f"{path.name} changed (sha256 {digest[:12]}...). Gate thresholds are "
                         f"locked; update GATES_SHA256 in a reviewed commit if this is intended.")
    return json.loads(path.read_text(encoding="utf-8"))


def _condition(name: str, value: float | None, threshold: float, at_least: bool) -> dict:
    passed = value is not None and (value >= threshold if at_least else value <= threshold)
    return {"name": name, "value": value, "threshold": threshold,
            "direction": ">=" if at_least else "<=", "passed": passed}


def evaluate(gates: dict, gold: dict[str, list[dict]], candidate: dict[str, list[dict]],
             baseline: dict[str, list[dict]] | None = None) -> dict:
    test = score(gold["test"], candidate["test"])
    real = score(gold["gold"], candidate["gold"])
    t, g = gates["test"], gates["gold"]
    conditions = [
        _condition("test.exact_match", test["exact_match"], t["min_exact_match"], True),
        _condition("test.invalid_rate", test["invalid_rate"], t["max_invalid_rate"], False),
        _condition("test.noise_false_positive_rate", test["noise_false_positive_rate"],
                   t["max_noise_false_positive_rate"], False),
        *[_condition(f"test.recall.{check}", stats["recall"], t["min_check_recall"], True)
          for check, stats in test["per_check"].items() if stats["support"]],
        _condition("gold.micro_recall", real["micro_recall"], g["min_micro_recall"], True),
        _condition("gold.invalid_rate", real["invalid_rate"], g["max_invalid_rate"], False),
    ]
    report = {"test": test, "gold": real}
    if baseline is not None:
        base = score(gold["gold"], baseline["gold"])
        report["baseline_gold"] = base
        conditions.append(_condition("gold.exact_match_minus_baseline",
                                     real["exact_match"] - base["exact_match"],
                                     g["min_exact_match_minus_baseline"], True))
    report["conditions"] = conditions
    report["passed"] = all(c["passed"] for c in conditions)
    return report


def evaluate_runs(gates: dict, gold: dict[str, list[dict]],
                  candidates: dict[str, dict[str, list[dict]]],
                  baseline: dict[str, list[dict]] | None = None) -> dict:
    """Every independent training run must pass; one lucky run is not parity."""
    runs = {name: evaluate(gates, gold, preds, baseline) for name, preds in candidates.items()}
    needed = gates["robustness"]["min_independent_runs"]
    count = _condition("runs.independent_count", len(runs), needed, True)
    return {"runs": runs, "run_count_condition": count,
            "passed": count["passed"] and all(r["passed"] for r in runs.values())}
