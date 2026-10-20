import pytest

from email_workshop.persona_evaluation import (
    aggregate_rows,
    chrf,
    cohen_kappa,
    create_blinded_review_rows,
    distinct_n,
    heuristic_risk_flags,
    paired_bootstrap,
    paired_sign_test,
    rouge_l_f1,
    score_rows,
    token_prf,
)


def test_reference_metrics_reward_identical_text():
    expected = "Please send the owner and deadline."
    assert token_prf(expected, expected) == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }
    assert rouge_l_f1(expected, expected) == 1.0
    assert chrf(expected, expected) == 1.0
    assert 0 < token_prf(expected, "Please send the deadline.")["f1"] < 1


def test_risk_flags_are_visible():
    result = heuristic_risk_flags(
        "Invoice",
        "Please review the invoice.",
        "Never approve payments.",
        "I approve payment of $9,000 on Friday.",
    )
    assert result["commitment_language"]
    assert result["unsupported_numbers"] == ["$9,000"]
    assert result["unsupported_dates"] == ["Friday"]
    assert result["has_risk_flag"]


def test_scoring_aggregation_and_paired_statistics():
    source = {
        "one": {"subject": "Update", "body": "Please review."},
        "two": {"subject": "Reminder", "body": "Reply by Friday."},
    }
    base_predictions = [
        {
            "id": "one",
            "expected": "Please share the owner.",
            "generated": "Thanks.",
            "latency_ms": 20.0,
        },
        {
            "id": "two",
            "expected": "I will review by Friday.",
            "generated": "Noted.",
            "latency_ms": 30.0,
        },
    ]
    adapted_predictions = [
        {
            "id": "one",
            "expected": "Please share the owner.",
            "generated": "Please share the owner.",
            "latency_ms": 10.0,
        },
        {
            "id": "two",
            "expected": "I will review by Friday.",
            "generated": "I will review by Friday.",
            "latency_ms": 15.0,
        },
    ]
    base = score_rows(base_predictions, source, "profile")
    adapted = score_rows(adapted_predictions, source, "profile")
    assert aggregate_rows(adapted)["token_f1"] == 1
    bootstrap = paired_bootstrap(base, adapted, "token_f1", samples=200)
    assert bootstrap["mean_delta"] > 0
    assert bootstrap["probability_improvement"] == 1
    sign = paired_sign_test(base, adapted, "token_f1")
    assert sign["wins"] == 2 and sign["losses"] == 0


def test_blinding_diversity_and_kappa():
    source = [
        {"id": "one", "subject": "A", "body": "B"},
        {"id": "two", "subject": "C", "body": "D"},
    ]
    base = [
        {"id": "one", "generated": "base one"},
        {"id": "two", "generated": "base two"},
    ]
    adapted = [
        {"id": "one", "generated": "adapted one"},
        {"id": "two", "generated": "adapted two"},
    ]
    rows, key = create_blinded_review_rows(source, base, adapted)
    assert len(rows) == len(key) == 2
    assert set(key.values()) <= {"A", "B"}
    assert distinct_n([row["response_a"] for row in rows], 1) > 0
    assert cohen_kappa(["A", "B", "A"], ["A", "B", "A"]) == 1
    with pytest.raises(ValueError):
        cohen_kappa([], [])
