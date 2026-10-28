"""Optional typed email classification (Phase 5C).

Two taxonomies with separate contracts:

* ``C6``  - one six-way ``Choice`` (multiclass) reproducing the CLM notebook benchmark.
* ``C10`` - ten independent yes/no ``Choice`` questions (multilabel) over the email workshop
  labels. All positive decisions are kept; there is **no argmax across labels**.

Backends: ``clm`` (real CLM server, strict health check, mock rejected by default) and
``lexical`` (TF-IDF + logistic regression exported to JSON by ``scripts/classification_k0.py``;
C10 only). A failing backend yields ``status: "unavailable"`` - never a silent fallback.

The classifier sees only ``subject`` and ``body``. Its labels can suggest evidence domains or
review; they never select a persona or authorize anything.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import requests

TAXONOMY_VERSION = {"C6": "c6-v1", "C10": "c10-v1"}

C6_CRITERIA = {
    "forum": "Posts, replies, or digests from online discussion forums and community boards.",
    "promotions": "Marketing offers, sales, discounts, and product advertising.",
    "social_media": "Notifications from social networks about connections, posts, or messages.",
    "spam": "Unsolicited, deceptive, or junk messages, including scams.",
    "updates": "Transactional or account updates: receipts, statements, shipping, service news.",
    "verify_code": "One-time passcodes, verification codes, or sign-in confirmation messages.",
}
C6_INSTRUCTIONS = "Which single category best describes this email? (c6-v1)"

C10_DEFINITIONS = {
    "Business": "work matters between colleagues or companies: projects, meetings, operations",
    "Customer Support": "a customer asking for help, reporting a problem, or support replying",
    "Events & Invitations": "invitations, event logistics, RSVPs, or scheduled gatherings",
    "Finance & Bills": "invoices, payments, bills, budgets, refunds, or financial approvals",
    "Job Application": "job applications, recruiting, interviews, or hiring decisions",
    "Newsletters": "recurring editorial newsletters or digests sent to a subscriber list",
    "Personal": "personal, non-work correspondence with friends or family",
    "Promotions": "marketing offers, discounts, or product advertising",
    "Reminders": "reminders about deadlines, appointments, renewals, or pending actions",
    "Travel & Bookings": "flights, hotels, itineraries, reservations, or travel arrangements",
}


def c10_key(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def c10_questions() -> dict[str, dict[str, Any]]:
    """Wire-format C10 questions: one binary Choice per label (stable yes/no keys)."""
    return {
        c10_key(label): {
            "type": "choice",
            "instructions": f"Is this email about {definition}? (c10-v1)",
            "criteria": {
                "yes": f"The email is in the '{label}' category: {definition}.",
                "no": f"The email is not in the '{label}' category.",
            },
        }
        for label, definition in C10_DEFINITIONS.items()
    }


def c6_questions() -> dict[str, dict[str, Any]]:
    return {"c6": {"type": "choice", "instructions": C6_INSTRUCTIONS, "criteria": C6_CRITERIA}}


def criteria_hash(taxonomy: str) -> str:
    questions = c6_questions() if taxonomy == "C6" else c10_questions()
    canonical = json.dumps(questions, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


class ClassifierUnavailable(Exception):
    pass


def _validate_distribution(name: str, probs: dict[str, Any], keys: set[str]) -> dict[str, float]:
    if set(probs) != keys:
        raise ClassifierUnavailable(f"{name}: expected keys {sorted(keys)}, got {sorted(probs)}")
    out = {}
    for key, value in probs.items():
        value = float(value)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ClassifierUnavailable(f"{name}: invalid probability {value!r} for {key}")
        out[key] = value
    if abs(sum(out.values()) - 1.0) > 1e-3:
        raise ClassifierUnavailable(f"{name}: probabilities sum to {sum(out.values()):.4f}")
    return out


@dataclass
class ClassifierSettings:
    backend: str = "none"            # none | clm | lexical
    clm_url: str = "http://127.0.0.1:8700"
    clm_model: str = "clm-latest"
    clm_timeout: float = 60.0
    temperature: float | None = None
    allow_mock: bool = False         # wiring labs only; results are flagged real_backend=false
    lexical_artifact: str | None = None
    abstain_below: float = 0.5       # C6: top-1 probability needed to avoid review
    review_margin: float = 0.1       # C10: |p - threshold| below this flags the label for review
    calibration_version: str = "uncalibrated-v0"
    max_chars: int = 4000

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> ClassifierSettings:
        raw = raw or {}
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


def _base_record(taxonomy: str, backend: str, settings: ClassifierSettings) -> dict[str, Any]:
    return {
        "taxonomy": taxonomy,
        "taxonomy_version": TAXONOMY_VERSION[taxonomy],
        "task_type": "multiclass" if taxonomy == "C6" else "multilabel",
        "backend": backend,
        "criteria_hash": criteria_hash(taxonomy),
        "calibration_version": settings.calibration_version,
        "temperature": settings.temperature,
        "truncation": {"max_chars": settings.max_chars},
    }


def _state(subject: str, body: str, max_chars: int) -> dict[str, str]:
    return {"subject": subject[:500], "body": body[:max_chars]}


# ---- CLM backend ---------------------------------------------------------------------
def _clm_health(settings: ClassifierSettings) -> dict[str, Any]:
    try:
        health = requests.get(f"{settings.clm_url.rstrip('/')}/health", timeout=5).json()
    except (requests.RequestException, ValueError) as exc:
        raise ClassifierUnavailable(f"CLM server unreachable: {exc}") from exc
    if not health.get("ok"):
        raise ClassifierUnavailable("CLM server reports not ok.")
    if not health.get("embedder"):
        raise ClassifierUnavailable("CLM embedding service is unhealthy.")
    if settings.clm_model not in (health.get("models") or []):
        raise ClassifierUnavailable(f"CLM model '{settings.clm_model}' is not served.")
    if health.get("mock") and not settings.allow_mock:
        raise ClassifierUnavailable("CLM server is the mock playground; mock is rejected.")
    return health


def classify_clm(
    taxonomy: str, subject: str, body: str, settings: ClassifierSettings
) -> dict[str, Any]:
    health = _clm_health(settings)
    try:
        from clm import Choice, CLMClient
    except ImportError as exc:
        raise ClassifierUnavailable("The 'clm' client package is not installed.") from exc
    wire = c6_questions() if taxonomy == "C6" else c10_questions()
    questions = {
        name: Choice(criteria=q["criteria"], instructions=q["instructions"])
        for name, q in wire.items()
    }
    started = time.perf_counter()
    try:
        with CLMClient(base_url=settings.clm_url, timeout=settings.clm_timeout) as client:
            response = client.system_one(
                state=_state(subject, body, settings.max_chars),
                questions=questions,
                model=settings.clm_model,
                temperature=settings.temperature,
            )
    except Exception as exc:
        raise ClassifierUnavailable(f"CLM request failed: {exc}") from exc
    record = _base_record(taxonomy, "clm", settings)
    record.update({
        "model": response.model,
        "real_backend": not health.get("mock", False),
        "latency_ms": response.latency_ms or round((time.perf_counter() - started) * 1000, 1),
    })
    answers = {}
    for name, q in wire.items():
        answer = response.answers.get(name)
        if answer is None or not hasattr(answer, "probabilities"):
            raise ClassifierUnavailable(f"CLM answer missing for '{name}'.")
        answers[name] = _validate_distribution(name, answer.probabilities, set(q["criteria"]))
    return _finish(taxonomy, record, answers, settings, score_type="clm_choice_probability")


# ---- lexical backend -----------------------------------------------------------------
TOKEN = re.compile(r"[a-z0-9]+")


def lexical_features(text: str) -> list[str]:
    tokens = TOKEN.findall(text.lower())
    return tokens + [f"{a} {b}" for a, b in pairwise(tokens)]


def lexical_scores(artifact: dict[str, Any], subject: str, body: str) -> dict[str, float]:
    """Pure-Python inference matching sklearn TfidfVectorizer(sublinear_tf, l2) + LR."""
    vocab, idf = artifact["vocabulary"], artifact["idf"]
    counts = Counter(f for f in lexical_features(f"{subject}\n{body}") if f in vocab)
    vector = {vocab[f]: (1 + math.log(c)) * idf[vocab[f]] for f, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in vector.values())) or 1.0
    scores = {}
    for label, coef, intercept in zip(artifact["labels"], artifact["coef"], artifact["intercept"]):
        z = intercept + sum(coef[i] * v / norm for i, v in vector.items())
        scores[label] = 1 / (1 + math.exp(-z))
    return scores


def classify_lexical(
    taxonomy: str, subject: str, body: str, settings: ClassifierSettings
) -> dict[str, Any]:
    if taxonomy != "C10":
        raise ClassifierUnavailable("The lexical artifact is trained for C10 only.")
    if not settings.lexical_artifact or not Path(settings.lexical_artifact).is_file():
        raise ClassifierUnavailable("Lexical artifact not found; run scripts/classification_k0.py.")
    raw = Path(settings.lexical_artifact).read_bytes()
    artifact = json.loads(raw)
    if artifact.get("taxonomy_version") != TAXONOMY_VERSION["C10"]:
        raise ClassifierUnavailable("Lexical artifact taxonomy version mismatch.")
    started = time.perf_counter()
    scores = lexical_scores(artifact, subject, body[: settings.max_chars])
    answers = {
        c10_key(label): {"yes": p, "no": 1 - p} for label, p in scores.items()
    }
    record = _base_record(taxonomy, "lexical", settings)
    record.update({
        "model": artifact.get("model", "tfidf-logreg"),
        "artifact_hash": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "real_backend": True,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    })
    thresholds = {c10_key(k): v for k, v in artifact.get("thresholds", {}).items()}
    return _finish(taxonomy, record, answers, settings, "logistic_probability", thresholds)


# ---- shared --------------------------------------------------------------------------
def _finish(
    taxonomy: str, record: dict[str, Any], answers: dict[str, dict[str, float]],
    settings: ClassifierSettings, score_type: str, thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    record["score_type"] = score_type
    record["status"] = "ok"
    if taxonomy == "C6":
        probs = answers["c6"]
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)
        top_label, top_p = ranked[0]
        abstain = top_p < settings.abstain_below
        record.update({
            "scores": probs,
            "label": None if abstain else top_label,
            "top2": [k for k, _ in ranked[:2]],
            "abstained": abstain,
            "review_state": "needs_review" if abstain else "none",
        })
        return record
    thresholds = thresholds or {}
    labels, uncertain, scores = [], [], {}
    for label in C10_DEFINITIONS:
        key = c10_key(label)
        p_yes = answers[key]["yes"]
        threshold = thresholds.get(key, 0.5)
        scores[label] = round(p_yes, 6)
        if p_yes >= threshold:
            labels.append(label)
        if abs(p_yes - threshold) < settings.review_margin:
            uncertain.append(label)
    record.update({
        "scores": scores,
        "thresholds": {label: thresholds.get(c10_key(label), 0.5) for label in C10_DEFINITIONS},
        "labels": labels,
        "empty_prediction": not labels,
        "uncertain_labels": uncertain,
        "abstained": False,
        "review_state": "needs_review" if uncertain or not labels else "none",
    })
    return record


def classify(
    taxonomy: str, subject: str, body: str, settings: ClassifierSettings
) -> dict[str, Any]:
    """Return a classification record. Failures return ``status: unavailable`` explicitly."""
    if taxonomy not in TAXONOMY_VERSION:
        raise ValueError("taxonomy must be C6 or C10.")
    try:
        if settings.backend == "clm":
            return classify_clm(taxonomy, subject, body, settings)
        if settings.backend == "lexical":
            return classify_lexical(taxonomy, subject, body, settings)
        raise ClassifierUnavailable("No classifier backend is configured (classifier.backend).")
    except ClassifierUnavailable as exc:
        record = _base_record(taxonomy, settings.backend, settings)
        record.update({"status": "unavailable", "error": str(exc), "real_backend": False,
                       "labels" if taxonomy == "C10" else "label": None})
        return record
