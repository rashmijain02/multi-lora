"""Router metrics in plain Python so learners can audit every number.

A prediction row is ``{"id", "checks": list | None, "dropped": list, "latency_ms": float}``.
``checks is None`` means the model output could not be parsed: the router reports
*unavailable* and that row counts as wrong. There is no silent fallback.
"""

from __future__ import annotations

from statistics import median

from slm_router.labels import CHECK_ORDER


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score(gold: list[dict], predictions: list[dict]) -> dict:
    by_id = {p["id"]: p for p in predictions}
    missing = [g["id"] for g in gold if g["id"] not in by_id]
    if missing:
        raise ValueError(f"{len(missing)} gold rows have no prediction, e.g. {missing[:3]}")

    tp = {c: 0 for c in CHECK_ORDER}
    fp = dict(tp)
    fn = dict(tp)
    exact = invalid = dropped = noise_rows = noise_fp = 0
    latencies = []
    errors = []
    for g in gold:
        p = by_id[g["id"]]
        truth = set(g["checks"])
        if p["checks"] is None:
            invalid += 1
            pred: set[str] = set()
        else:
            pred = set(p["checks"])
        dropped += len(p.get("dropped", []))
        if p.get("latency_ms") is not None:
            latencies.append(p["latency_ms"])
        if p["checks"] is not None and pred == truth:
            exact += 1
        else:
            errors.append({"id": g["id"], "persona": g["persona"], "truth": sorted(truth),
                           "pred": None if p["checks"] is None else sorted(pred)})
        if not truth:
            noise_rows += 1
            noise_fp += bool(pred)
        for c in CHECK_ORDER:
            tp[c] += c in pred and c in truth
            fp[c] += c in pred and c not in truth
            fn[c] += c not in pred and c in truth

    all_tp, all_fp, all_fn = sum(tp.values()), sum(fp.values()), sum(fn.values())
    precision = _ratio(all_tp, all_tp + all_fp)
    recall = _ratio(all_tp, all_tp + all_fn)
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall and precision + recall else None)
    latencies.sort()
    return {
        "rows": len(gold),
        "exact_match": exact / len(gold),
        "exact_match_count": exact,
        "invalid_rate": invalid / len(gold),
        "micro_precision": precision,
        "micro_recall": recall,
        "micro_f1": f1,
        "per_check": {c: {"support": tp[c] + fn[c],
                          "recall": _ratio(tp[c], tp[c] + fn[c]),
                          "precision": _ratio(tp[c], tp[c] + fp[c])} for c in CHECK_ORDER},
        "noise_rows": noise_rows,
        "noise_false_positive_rate": _ratio(noise_fp, noise_rows),
        "out_of_scope_dropped": dropped,
        "latency_ms_p50": median(latencies) if latencies else None,
        "latency_ms_p95": latencies[int(0.95 * (len(latencies) - 1))] if latencies else None,
        "errors": errors,
    }
