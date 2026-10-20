from pathlib import Path

import numpy as np
import pytest

from email_workshop.data import (
    DOMAINS,
    LABELS,
    fingerprint,
    load_splits,
    messages,
    read_json,
    validate_rows,
    write_json,
)
from email_workshop.evaluation import evaluate, parse_labels, score
from email_workshop.persona import (
    load_persona_dataset,
    load_persona_registry,
    persona_messages,
    persona_paths,
    score_persona,
)
from email_workshop.routing import fit_router, select_domains


def test_real_taxonomy_is_multilabel():
    row = {"subject": "Review", "body": "Meeting tomorrow", "labels": ["Business", "Reminders"]}
    rows, audit = validate_rows([row, {**row, "subject": " REVIEW "}])
    assert len(rows) == 1 and len(rows[0]["labels"]) == 2
    assert audit["repeated_text_rows"] == 1
    assert set().union(*map(set, DOMAINS.values())) == set(LABELS)
    assert sum(map(len, DOMAINS.values())) == len(LABELS)


def test_conflicting_duplicates_are_quarantined(caplog):
    row = {"subject": "Review", "body": "Meeting tomorrow", "labels": ["Business"]}
    rows, audit = validate_rows([row, {**row, "labels": ["Business", "Reminders"]}])
    assert not rows
    assert audit["conflicting_texts_removed"] == 1
    assert "Quarantining" in caplog.text


@pytest.mark.parametrize("labels", [["unknown"], [], ["Business", "Business"], "Business", [None]])
def test_schema_rejects_invalid_labels(labels):
    with pytest.raises(ValueError, match="labels"):
        validate_rows([{"subject": "subject", "body": "body", "labels": labels}])


def test_disjoint_reproducible_splits_and_integrity(prepared):
    splits, manifest = load_splits(prepared)
    ids = [row["id"] for rows in splits.values() for row in rows]
    assert len(ids) == len(set(ids)) == 200
    assert all(
        {label for row in rows for label in row["labels"]} == set(LABELS)
        for rows in splits.values()
    )
    assert fingerprint(splits["test"]) == manifest["splits"]["test"]["sha256"]
    test_file = prepared / "data" / "test.json"
    rows = read_json(test_file)
    rows[0]["labels"] = ["Promotions"]
    write_json(test_file, rows)
    with pytest.raises(ValueError, match="manifest"):
        load_splits(prepared)


def test_router_only_uses_train_and_validation(prepared):
    router, metadata = fit_router(prepared)
    assert metadata["selection_split"] == "validation"
    assert metadata["validation_domain_recall"] >= 0.95
    assert metadata["validation_mean_calls"] <= 3
    domains = router.domains("Invoice", "Please pay your finance bill")
    assert domains and set(domains) <= set(DOMAINS)
    assert select_domains(np.array([0.1, 0.2, 0.05]), 0.9) == ["finance"]
    assert not any("expected" in message["content"] for message in messages("s", "b", LABELS))


def test_evaluation_refit_preserves_selected_router_target(prepared):
    _, configured = fit_router(prepared, target_recall=0.9)
    _, refitted = fit_router(prepared)
    assert refitted == configured
    assert refitted["target_recall"] == 0.9


@pytest.mark.parametrize(
    "response",
    [
        "```json\n[]\n```",
        '{"labels":[]}',
        '["Finance"]',
        '["Business","Business"]',
        "[1]",
    ],
)
def test_strict_model_output(response):
    with pytest.raises(ValueError):
        parse_labels(response, LABELS)
    assert parse_labels("[]", LABELS) == []


def test_out_of_domain_output_fails():
    with pytest.raises(ValueError, match="out-of-domain"):
        parse_labels('["Finance & Bills"]', DOMAINS["operations"])


class FakeBackend:
    def __init__(self, response="[]"):
        self.identity = {"backend": "unit-test-not-a-quality-model"}
        self.response = response
        self.calls = []

    def generate(self, subject, body, adapter):
        self.calls.append((subject, body, adapter))
        return self.response


def test_evaluation_resume_and_errors_are_visible(prepared):
    splits, _ = load_splits(prepared)
    router, metadata = fit_router(prepared)
    backend = FakeBackend("not JSON")
    output = prepared / "results.json"
    rows = splits["validation"][:3]
    result = evaluate(rows, backend, router, metadata, "base", output, "validation")
    summary, per_label = score(result)
    assert summary["invalid_output_rate"] == 1
    assert summary["valid_exact_match"] == 0
    assert summary["rows"] == 3 and len(per_label) == 10
    evaluate(rows, backend, router, metadata, "base", output, "validation")
    assert len(backend.calls) == 3
    with pytest.raises(ValueError, match="different run"):
        evaluate(rows, backend, router, metadata, "generalist", output, "validation")


def test_routed_and_all_specialists_have_same_holdout(prepared):
    splits, _ = load_splits(prepared)
    router, metadata = fit_router(prepared)
    rows = splits["test"][:5]
    all_rows = evaluate(
        rows, FakeBackend(), router, metadata, "all-specialists", prepared / "all.json", "test"
    )
    routed = evaluate(
        rows, FakeBackend(), router, metadata, "routed", prepared / "routed.json", "test"
    )
    assert [row["id"] for row in all_rows] == [row["id"] for row in routed]
    assert all(row["calls"] == 3 for row in all_rows)
    assert all(1 <= row["calls"] <= 3 for row in routed)
    assert score(all_rows)[0]["routing_label_coverage_ceiling"] == 1.0


def test_no_success_fallback_on_backend_error(prepared):
    class FailedBackend(FakeBackend):
        def generate(self, subject, body, adapter):
            raise RuntimeError("endpoint unavailable")

    splits, _ = load_splits(prepared)
    router, metadata = fit_router(prepared)
    output = prepared / "failed.json"
    with pytest.raises(RuntimeError, match="unavailable"):
        evaluate(
            splits["validation"][:1],
            FailedBackend(),
            router,
            metadata,
            "base",
            output,
            "validation",
        )
    assert not output.exists()


def test_persona_registry_and_committed_data_match():
    root = Path(__file__).resolve().parents[1]
    registry = load_persona_registry(root)
    assert len(registry) == 10
    assert len({item["adapter"] for item in registry.values()}) == 10
    splits, spec, profile, manifest = load_persona_dataset(root, "maya-chen-ceo")
    assert spec["name"] == "Maya Chen"
    assert profile.startswith("# Maya Chen")
    assert {name: len(rows) for name, rows in splits.items()} == {
        "train": 1473,
        "validation": 312,
        "test": 318,
    }
    assert manifest["rows"] == 2103
    assert manifest["test_policy"] == "sealed until final evaluation"
    wrong_file = root / registry["daniel-okafor-cfo"]["data_file"]
    with pytest.raises(ValueError, match="must match"):
        persona_paths(root, "maya-chen-ceo", wrong_file)


def test_persona_prompt_and_reference_metrics():
    root = Path(__file__).resolve().parents[1]
    _, spec, profile, _ = load_persona_dataset(root, "priya-raman-support")
    prompt = persona_messages(spec, profile, "Login issue", "The sign-in page returns an error.")
    assert [item["role"] for item in prompt] == ["system", "user"]
    assert spec["name"] in prompt[0]["content"]
    assert profile in prompt[0]["content"]
    assert "Return only the reply body" in prompt[0]["content"]
    predictions = [
        {
            "id": "one",
            "expected": "Thank you for the update.",
            "generated": "Thank you for the update.",
            "valid": True,
            "latency_ms": 10.0,
        },
        {
            "id": "two",
            "expected": "Please share the exact error.",
            "generated": "Please share the error text.",
            "valid": True,
            "latency_ms": 20.0,
        },
    ]
    metrics = score_persona(predictions)
    assert metrics["rows"] == 2
    assert metrics["nonempty_rate"] == 1
    assert 0 < metrics["mean_token_f1"] <= 1
    assert 0 < metrics["mean_rouge_l"] <= 1


def test_notebooks_have_clear_gates_and_no_outputs():
    nbformat = pytest.importorskip("nbformat")
    root = Path(__file__).resolve().parents[1]
    notebooks = sorted((root / "notebooks").glob("*.ipynb"))
    assert len(notebooks) == 7
    model_notebooks = {
        "02_train_email_adapters.ipynb",
        "03_compare_and_serve.ipynb",
        "05_train_persona_adapter.ipynb",
        "06_compare_persona_responses.ipynb",
        "07_persona_evaluation_techniques.ipynb",
    }
    for path in notebooks:
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        assert notebook.cells[0].cell_type == "markdown"
        config = next(cell for cell in notebook.cells if cell.get("id") == "config")
        if path.name in model_notebooks:
            assert "MODEL_CHOICE" in config.source
            assert "resolve_model_profile" in config.source
        if path.name.startswith(("04_", "05_", "06_")):
            assert "CLIENT_ID" in config.source
            assert "INPUT_FILE" in config.source
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                compile(cell.source, f"{path.name}:{index}", "exec")
