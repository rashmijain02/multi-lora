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


def test_notebooks_have_clear_gates_and_no_outputs():
    nbformat = pytest.importorskip("nbformat")
    root = Path(__file__).resolve().parents[1]
    notebooks = sorted((root / "notebooks").glob("*.ipynb"))
    assert len(notebooks) == 3
    for path in notebooks:
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        assert notebook.cells[0].cell_type == "markdown"
        config = next(cell for cell in notebook.cells if cell.get("id") == "config")
        if path.name != "01_email_data_and_routing.ipynb":
            assert "MODEL_CHOICE" in config.source
            assert "resolve_model_profile" in config.source
        for index, cell in enumerate(notebook.cells):
            if cell.cell_type == "code":
                assert cell.outputs == [] and cell.execution_count is None
                compile(cell.source, f"{path.name}:{index}", "exec")
