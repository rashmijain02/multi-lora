"""K0 router baseline: TF-IDF + one logistic regression per check.

Same protocol as PersonaDesk's ``classification_k0.py``: fit on ``train``, pick one threshold per
check on ``val`` only, then predict ``val``, ``test`` and ``gold``. The persona mask runs after
the model, exactly as it does for the SLM student, so the two are compared like for like.
"""

from __future__ import annotations

import time

import numpy as np

from slm_router.labels import CHECK_ORDER, persona_mask


def text(row: dict) -> str:
    return f"persona {row['persona']}\n{row['subject']}\n{row['body']}"


def targets(rows: list[dict]) -> np.ndarray:
    return np.array([[c in r["checks"] for c in CHECK_ORDER] for r in rows], dtype=int)


def fit_predict(splits: dict[str, list[dict]], seed: int = 2026) -> tuple[dict, dict]:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import f1_score

    vectorizer = TfidfVectorizer(lowercase=True, token_pattern=r"[a-z0-9]+", ngram_range=(1, 2),
                                 sublinear_tf=True, min_df=2)
    x_train = vectorizer.fit_transform([text(r) for r in splits["train"]])
    y_train = targets(splits["train"])
    models = [LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000,
                                 random_state=seed).fit(x_train, y_train[:, i])
              for i in range(len(CHECK_ORDER))]

    def proba(rows: list[dict]) -> np.ndarray:
        x = vectorizer.transform([text(r) for r in rows])
        return np.column_stack([m.predict_proba(x)[:, 1] for m in models])

    p_val, y_val = proba(splits["val"]), targets(splits["val"])
    grid = np.round(np.arange(0.05, 0.96, 0.05), 2)
    thresholds = {}
    for i, check in enumerate(CHECK_ORDER):
        f1s = [f1_score(y_val[:, i], p_val[:, i] >= t, zero_division=0) for t in grid]
        thresholds[check] = float(grid[int(np.argmax(f1s))])
    t_vec = np.array([thresholds[c] for c in CHECK_ORDER])

    predictions = {}
    for name in ("val", "test", "gold"):
        rows = splits[name]
        start = time.perf_counter()
        hits = proba(rows) >= t_vec
        per_row_ms = (time.perf_counter() - start) * 1000 / max(len(rows), 1)
        out = []
        for row, mask in zip(rows, hits, strict=True):
            kept, dropped = persona_mask(row["persona"],
                                         [c for c, on in zip(CHECK_ORDER, mask, strict=True) if on])
            out.append({"id": row["id"], "checks": kept, "dropped": dropped,
                        "latency_ms": per_row_ms})
        predictions[name] = out
    info = {"model": "tfidf-logreg-k0", "thresholds": thresholds,
            "vocabulary_size": len(vectorizer.vocabulary_), "fit_rows": len(splits["train"])}
    return predictions, info
