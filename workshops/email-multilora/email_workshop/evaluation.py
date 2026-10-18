from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    hamming_loss,
    precision_recall_fscore_support,
)

from email_workshop.data import (
    DOMAINS,
    LABELS,
    Email,
    allowed_labels,
    fingerprint,
    label_matrix,
    messages,
    read_json,
    write_json,
)
from email_workshop.routing import Router

STRATEGIES = ("base", "generalist", "all-specialists", "routed")


class Backend(Protocol):
    identity: dict[str, Any]

    def generate(self, subject: str, body: str, adapter: str) -> str: ...


def parse_labels(text: str, allowed: tuple[str, ...]) -> list[str]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ValueError("Model output is not a JSON array.") from error
    if not isinstance(value, list) or any(not isinstance(label, str) for label in value):
        raise ValueError("Model output must be an array of label strings.")
    if len(value) != len(set(value)) or set(value) - set(allowed):
        raise ValueError("Model returned duplicate, unknown, or out-of-domain labels.")
    return [label for label in LABELS if label in value]


def evaluate(
    rows: list[Email],
    backend: Backend,
    router: Router,
    router_metadata: dict[str, Any],
    strategy: str,
    output: Path,
    split_name: str,
) -> list[dict[str, Any]]:
    if strategy not in STRATEGIES or split_name not in ("validation", "test"):
        raise ValueError("Unknown evaluation strategy or split.")
    contract = {
        "backend": backend.identity,
        "router": router_metadata,
        "strategy": strategy,
        "split": split_name,
        "rows_sha256": fingerprint(rows),
        "labels": LABELS,
        "version": 1,
        "prompt_contracts": {
            name: messages("", "", allowed_labels(name))
            for name in ("base", "generalist", *DOMAINS)
        },
    }
    signature = fingerprint(contract)
    results: list[dict[str, Any]] = []
    if output.exists():
        saved = read_json(output)
        if saved["fingerprint"] != signature:
            raise ValueError("Checkpoint belongs to a different run/configuration/row set.")
        results = saved["predictions"]
        if len(results) > len(rows) or [item["id"] for item in results] != [
            row["id"] for row in rows[: len(results)]
        ]:
            raise ValueError("Checkpoint IDs are not a prefix of this evaluation set.")
    for row in rows[len(results) :]:
        started = time.perf_counter()
        if strategy in ("base", "generalist"):
            selected = [strategy]
        elif strategy == "all-specialists":
            selected = list(DOMAINS)
        else:
            selected = router.domains(row["subject"], row["body"])
        predicted: set[str] = set()
        errors: list[dict[str, str]] = []
        for adapter in selected:
            # Transport/model failures propagate; only format failures become scored errors.
            response = backend.generate(row["subject"], row["body"], adapter)
            try:
                predicted.update(parse_labels(response, allowed_labels(adapter)))
            except ValueError as error:
                errors.append({"adapter": adapter, "error": str(error)})
        results.append(
            {
                "id": row["id"],
                "expected": row["labels"],
                "predicted": [label for label in LABELS if label in predicted],
                "selected_adapters": selected,
                "calls": len(selected),
                "latency_ms": (time.perf_counter() - started) * 1000,
                "errors": errors,
                "valid": not errors,
            }
        )
        write_json(
            output,
            {
                "fingerprint": signature,
                "contract": contract,
                "predictions": results,
            },
        )
    return results


def score(predictions: list[dict[str, Any]]) -> tuple[dict, list[dict]]:
    if not predictions or len({row["id"] for row in predictions}) != len(predictions):
        raise ValueError("Scoring needs non-empty predictions with unique IDs.")
    expected = np.array(
        [[int(label in row["expected"]) for label in LABELS] for row in predictions]
    )
    predicted = np.array(
        [[int(label in row["predicted"]) for label in LABELS] for row in predictions]
    )
    precision, recall, f1, support = precision_recall_fscore_support(
        expected, predicted, average=None, zero_division=0
    )
    exact = np.all(expected == predicted, axis=1)
    valid = np.array([row["valid"] for row in predictions])
    summary = {
        "rows": len(predictions),
        "exact_match": float(accuracy_score(expected, predicted)),
        "valid_exact_match": float((exact & valid).mean()),
        "micro_f1": float(f1_score(expected, predicted, average="micro", zero_division=0)),
        "macro_f1": float(f1_score(expected, predicted, average="macro", zero_division=0)),
        "hamming_loss": float(hamming_loss(expected, predicted)),
        "invalid_output_rate": float((~valid).mean()),
        "mean_model_calls": float(np.mean([row["calls"] for row in predictions])),
        "latency_p50_ms": float(np.percentile([row["latency_ms"] for row in predictions], 50)),
        "latency_p95_ms": float(np.percentile([row["latency_ms"] for row in predictions], 95)),
    }
    if all(set(row["selected_adapters"]) <= set(DOMAINS) for row in predictions):
        expected_domains = [
            {domain for domain, labels in DOMAINS.items() if set(row["expected"]) & set(labels)}
            for row in predictions
        ]
        denominator = sum(map(len, expected_domains))
        summary["routing_domain_recall"] = (
            sum(
                len(domains & set(row["selected_adapters"]))
                for row, domains in zip(predictions, expected_domains, strict=True)
            )
            / denominator
        )
        summary["routing_label_coverage_ceiling"] = sum(
            len(
                set(row["expected"])
                & {label for domain in row["selected_adapters"] for label in DOMAINS[domain]}
            )
            for row in predictions
        ) / int(expected.sum())
    per_label = [
        {
            "label": label,
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1[i]),
            "support": int(support[i]),
        }
        for i, label in enumerate(LABELS)
    ]
    return summary, per_label


def lexical_predictions(rows: list[Email], router: Router) -> list[dict]:
    result = []
    for row in rows:
        started = time.perf_counter()
        labels = router.labels(row["subject"], row["body"])
        result.append(
            {
                "id": row["id"],
                "expected": row["labels"],
                "predicted": labels,
                "selected_adapters": ["tfidf"],
                "calls": 0,
                "valid": True,
                "errors": [],
                "latency_ms": (time.perf_counter() - started) * 1000,
            }
        )
    return result


def binary_confusions(rows: list[dict]) -> dict[str, list[list[int]]]:
    from sklearn.metrics import multilabel_confusion_matrix

    expected = label_matrix(
        [{"id": row["id"], "subject": "", "body": "", "labels": row["expected"]} for row in rows]
    )
    predicted = np.array([[int(label in row["predicted"]) for label in LABELS] for row in rows])
    return dict(zip(LABELS, multilabel_confusion_matrix(expected, predicted).tolist(), strict=True))
