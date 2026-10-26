"""K0: lexical C10 baseline exported as a JSON artifact for the PersonaDesk classifier tool.

Protocol (PROPOSAL.md, classification workstream):
* fit on ``train`` minus a seeded 20% development partition;
* choose one threshold per label on that development partition only;
* report on ``validation``; the ``test`` split stays sealed unless ``--unseal-test``;
* export vocabulary/idf/coefficients as JSON (no pickle) and prove the plugin's pure-Python
  scorer reproduces scikit-learn probabilities.

Run from ``workshops/email-multilora`` with its prepared data directory (relative path):

    cd workshops/email-multilora
    uv run --with scikit-learn python ../personal-agent-multilora/scripts/classification_k0.py \
        --data-root artifacts/run-2026
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

PD_ROOT = Path(__file__).resolve().parents[1]
EMAIL_ROOT = PD_ROOT.parent / "email-multilora"
sys.path[:0] = [str(EMAIL_ROOT), str(PD_ROOT)]

from email_workshop.data import LABELS, fingerprint, label_matrix, load_splits

from hermes_plugin.classification import TAXONOMY_VERSION, lexical_scores


def text(row: dict) -> str:
    return f"{row['subject']}\n{row['body']}"


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    from sklearn.metrics import f1_score, precision_score, recall_score

    per_label = {
        label: {
            "precision": float(precision_score(y_true[:, i], y_pred[:, i], zero_division=0)),
            "recall": float(recall_score(y_true[:, i], y_pred[:, i], zero_division=0)),
            "f1": float(f1_score(y_true[:, i], y_pred[:, i], zero_division=0)),
            "support": int(y_true[:, i].sum()),
        }
        for i, label in enumerate(LABELS)
    }
    return {
        "micro_f1": float(f1_score(y_true, y_pred, average="micro", zero_division=0)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "exact_set_match": float((y_true == y_pred).all(axis=1).mean()),
        "empty_predictions": int((y_pred.sum(axis=1) == 0).sum()),
        "rows": len(y_true),
        "per_label": per_label,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-root", required=True,
                        help="Email workshop artifact dir, relative to workshops/email-multilora")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--unseal-test", action="store_true")
    args = parser.parse_args()
    if Path(args.data_root).is_absolute() or ".." in Path(args.data_root).parts:
        parser.error("--data-root must be relative to workshops/email-multilora")

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score
    from sklearn.model_selection import train_test_split

    splits, manifest = load_splits(EMAIL_ROOT / args.data_root)
    train_rows, dev_rows = train_test_split(splits["train"], test_size=0.2,
                                            random_state=args.seed)
    vectorizer = TfidfVectorizer(lowercase=True, token_pattern=r"[a-z0-9]+", ngram_range=(1, 2),
                                 sublinear_tf=True, min_df=2, norm="l2")
    x_train = vectorizer.fit_transform([text(r) for r in train_rows])
    y_train = label_matrix(train_rows)
    models = [
        LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000).fit(x_train, y_train[:, i])
        for i in range(len(LABELS))
    ]

    def proba(rows: list[dict]) -> np.ndarray:
        x = vectorizer.transform([text(r) for r in rows])
        return np.column_stack([m.predict_proba(x)[:, 1] for m in models])

    p_dev, y_dev = proba(dev_rows), label_matrix(dev_rows)
    grid = np.round(np.arange(0.05, 0.96, 0.05), 2)
    thresholds = {}
    for i, label in enumerate(LABELS):
        scores = [f1_score(y_dev[:, i], p_dev[:, i] >= t, zero_division=0) for t in grid]
        thresholds[label] = float(grid[int(np.argmax(scores))])
    t_vec = np.array([thresholds[label] for label in LABELS])

    report = {
        "task": "K0", "taxonomy": "C10", "taxonomy_version": TAXONOMY_VERSION["C10"],
        "data_manifest_fingerprint": fingerprint(manifest),
        "partition": {"fit": len(train_rows), "threshold_dev": len(dev_rows),
                      "validation": len(splits["validation"]),
                      "test": "sealed" if not args.unseal_test else len(splits["test"])},
        "thresholds": thresholds,
        "development": metrics(y_dev, (p_dev >= t_vec).astype(int)),
        "validation": metrics(label_matrix(splits["validation"]),
                              (proba(splits["validation"]) >= t_vec).astype(int)),
    }
    if args.unseal_test:
        report["test"] = metrics(label_matrix(splits["test"]),
                                 (proba(splits["test"]) >= t_vec).astype(int))

    artifact = {
        "taxonomy_version": TAXONOMY_VERSION["C10"],
        "model": "tfidf-logreg-k0",
        "labels": list(LABELS),
        "vocabulary": {k: int(v) for k, v in vectorizer.vocabulary_.items()},
        "idf": [float(v) for v in vectorizer.idf_],
        "coef": [[float(c) for c in m.coef_[0]] for m in models],
        "intercept": [float(m.intercept_[0]) for m in models],
        "thresholds": thresholds,
        "data_manifest_fingerprint": report["data_manifest_fingerprint"],
    }
    sample = splits["validation"][:50]
    sk = proba(sample)
    py = np.array([[lexical_scores(artifact, r["subject"], r["body"])[label] for label in LABELS]
                   for r in sample])
    report["pure_python_parity_max_abs_diff"] = float(np.abs(sk - py).max())
    if report["pure_python_parity_max_abs_diff"] > 1e-6:
        raise SystemExit("Pure-Python scorer does not match scikit-learn; artifact not written.")

    out = PD_ROOT / "artifacts" / "classification"
    out.mkdir(parents=True, exist_ok=True)
    (out / "c10_lexical.json").write_text(json.dumps(artifact), encoding="utf-8")
    (out / "k0_c10_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    v = report["validation"]
    print(f"K0 C10 validation: micro F1 {v['micro_f1']:.3f}, macro F1 {v['macro_f1']:.3f}, "
          f"exact match {v['exact_set_match']:.3f}, empty {v['empty_predictions']}")
    print("Wrote artifacts/classification/c10_lexical.json and k0_c10_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
