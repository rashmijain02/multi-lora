from __future__ import annotations

from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline

from email_workshop.data import (
    DOMAINS,
    Email,
    fingerprint,
    label_matrix,
    load_splits,
    read_json,
    write_json,
)


def email_text(subject: str, body: str) -> str:
    return f"{subject}\n{body}"


def domain_targets(rows: list[Email]) -> np.ndarray:
    return np.array(
        [
            [int(bool(set(row["labels"]) & set(labels))) for labels in DOMAINS.values()]
            for row in rows
        ]
    )


def select_domains(probabilities: np.ndarray, threshold: float) -> list[str]:
    if probabilities.shape != (len(DOMAINS),) or not np.isfinite(probabilities).all():
        raise ValueError("Router must return one finite probability per domain.")
    chosen = np.flatnonzero(probabilities >= threshold)
    if not len(chosen):
        chosen = np.array([int(np.argmax(probabilities))])
    return [list(DOMAINS)[index] for index in chosen]


def routing_mask(probabilities: np.ndarray, threshold: float) -> np.ndarray:
    result = np.zeros(probabilities.shape, dtype=int)
    for index, row in enumerate(probabilities):
        chosen = select_domains(row, threshold)
        result[index] = [int(name in chosen) for name in DOMAINS]
    return result


class Router:
    def __init__(self, model: Pipeline, label_threshold: float, route_threshold: float):
        self.model = model
        self.label_threshold = label_threshold
        self.route_threshold = route_threshold

    def probabilities(self, subject: str, body: str) -> np.ndarray:
        return self.model.predict_proba([email_text(subject, body)])[0]

    def labels(self, subject: str, body: str) -> list[str]:
        from email_workshop.data import LABELS

        return [
            name
            for name, probability in zip(LABELS, self.probabilities(subject, body), strict=True)
            if probability >= self.label_threshold
        ]

    def domains(self, subject: str, body: str) -> list[str]:
        from email_workshop.data import LABELS

        scores = dict(zip(LABELS, self.probabilities(subject, body), strict=True))
        # Max label probability is a routing score, not a calibrated union probability.
        domain_scores = np.array(
            [max(scores[label] for label in labels) for labels in DOMAINS.values()]
        )
        return select_domains(domain_scores, self.route_threshold)


def fit_router(root: Path, target_recall: float | None = None) -> tuple[Router, dict[str, Any]]:
    metadata_path = root / "router" / "metadata.json"
    previous = (
        read_json(metadata_path) if metadata_path.exists() and target_recall is None else None
    )
    if target_recall is None:
        target_recall = previous["target_recall"] if previous else 0.95
    if not 0 < target_recall <= 1:
        raise ValueError("target_recall must be in (0, 1].")
    from email_workshop.data import LABELS

    splits, manifest = load_splits(root)
    train, validation = splits["train"], splits["validation"]
    model = Pipeline(
        [
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000)),
            (
                "classifier",
                OneVsRestClassifier(
                    LogisticRegression(
                        solver="liblinear",
                        class_weight="balanced",
                        max_iter=1000,
                        random_state=manifest["seed"],
                    )
                ),
            ),
        ]
    )
    model.fit([email_text(row["subject"], row["body"]) for row in train], label_matrix(train))
    probabilities = model.predict_proba(
        [email_text(row["subject"], row["body"]) for row in validation]
    )
    y_validation = label_matrix(validation)
    label_threshold = max(
        np.linspace(0.1, 0.9, 17),
        key=lambda threshold: f1_score(
            y_validation, probabilities >= threshold, average="micro", zero_division=0
        ),
    )
    domain_scores = np.column_stack(
        [
            probabilities[:, [LABELS.index(label) for label in labels]].max(axis=1)
            for labels in DOMAINS.values()
        ]
    )
    expected = domain_targets(validation)
    trials = []
    for threshold in np.linspace(0.0, 0.95, 20):
        selected = routing_mask(domain_scores, float(threshold))
        recall = float((selected * expected).sum() / expected.sum())
        trials.append(
            {
                "threshold": float(threshold),
                "domain_recall": recall,
                "mean_calls": float(selected.sum(axis=1).mean()),
            }
        )
    feasible = [row for row in trials if row["domain_recall"] >= target_recall]
    best = min(feasible, key=lambda row: (row["mean_calls"], -row["threshold"]))
    selected = routing_mask(domain_scores, best["threshold"])
    router = Router(model, float(label_threshold), best["threshold"])
    metadata = {
        "data_fingerprint": fingerprint(manifest),
        "seed": manifest["seed"],
        "label_threshold": float(label_threshold),
        "route_threshold": best["threshold"],
        "validation_domain_recall": best["domain_recall"],
        "validation_mean_calls": best["mean_calls"],
        "validation_recall_by_domain": {
            name: float((selected[:, index] * expected[:, index]).sum() / expected[:, index].sum())
            for index, name in enumerate(DOMAINS)
        },
        "target_recall": target_recall,
        "selection_split": "validation",
        "router_kind": "TF-IDF + one-vs-rest logistic regression; no LLM",
        "versions": {name: version(name) for name in ("scikit-learn", "numpy")},
        "trials": trials,
    }
    if previous and fingerprint(previous) != fingerprint(metadata):
        raise ValueError("Refitted router differs from saved settings; start an explicit new run.")
    write_json(metadata_path, metadata)
    return router, metadata
