"""Train-only TF-IDF/logistic-regression baseline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .data import as_examples
from .dataset import MECHANISMS, Example


def fit_lexical_baseline(train_examples: Sequence[Example]) -> dict[str, Any]:
    """Fit one small lexical classifier per mechanism using train records only."""
    if not train_examples:
        raise ValueError("at least one training example is required")
    if any(example.split != "train" for example in train_examples):
        raise ValueError("baseline fitting accepts train examples only")

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    texts = [example.conversation_text for example in train_examples]
    models: dict[str, Any] = {}
    for mechanism in MECHANISMS:
        labels = [example.labels[mechanism].score for example in train_examples]
        if set(labels) != {0, 1, 2}:
            raise ValueError(f"train examples must include all three {mechanism} scores")
        model = make_pipeline(
            TfidfVectorizer(ngram_range=(1, 2), lowercase=True, sublinear_tf=True),
            LogisticRegression(class_weight="balanced", max_iter=500, random_state=17),
        )
        model.fit(texts, labels)
        models[mechanism] = model
    return models


def predict_baseline(
    models: dict[str, Any], examples: Sequence[Example | dict[str, Any]]
) -> dict[str, dict[str, int]]:
    """Return per-example integer predictions without altering evaluation records."""
    if set(models) != set(MECHANISMS):
        raise ValueError(f"models must contain exactly: {', '.join(MECHANISMS)}")
    examples = as_examples(examples)
    if any(example.split == "train" for example in examples):
        raise ValueError("baseline evaluation must not include train examples")
    texts = [example.conversation_text for example in examples]
    return {
        example.id: {
            mechanism: int(models[mechanism].predict([text])[0]) for mechanism in MECHANISMS
        }
        for example, text in zip(examples, texts, strict=True)
    }


def fit_baseline(train_records: Sequence[Example | dict[str, Any]]) -> dict[str, Any]:
    """Notebook-facing alias for the train-only lexical baseline."""
    return fit_lexical_baseline(as_examples(train_records))
