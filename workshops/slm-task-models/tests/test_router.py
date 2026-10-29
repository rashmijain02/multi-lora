"""Focused router tests. None need a GPU; the student's parser is tested as plain Python."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from slm_router.data import FIXTURES, ROOT, load_gold, workshop_path
from slm_router.gate import GATES_SHA256, evaluate, evaluate_runs, load_gates
from slm_router.labels import CHECKS, PERSONA_POLICIES, allowed_checks, persona_mask
from slm_router.metrics import score
from slm_router.student import parse_output
from slm_router.synth import POOLS, families, generate, generate_all

PD_ROOT = ROOT.parent / "personal-agent-multilora"


def test_label_space_matches_personadesk_checks_and_policies():
    tree = ast.parse((PD_ROOT / "hermes_plugin" / "checks.py").read_text(encoding="utf-8"))
    assign = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                  and getattr(n.target, "id", "") == "CHECKS")
    source = {k.value: v.elts[0].value for k, v in zip(assign.value.keys, assign.value.values,
                                                         strict=True)}
    assert source == CHECKS
    on_disk = {p.name: tuple(sorted(f.stem for f in p.glob("*.md")))
               for p in (PD_ROOT / "policies").iterdir() if p.is_dir()}
    assert on_disk == {k: tuple(sorted(v)) for k, v in PERSONA_POLICIES.items()}


def test_persona_mask_can_only_narrow_never_widen():
    kept, dropped = persona_mask("priya-raman-support", ["invoice_po_match", "sla_status"])
    assert kept == ["sla_status"] and dropped == ["invoice_po_match"]
    assert set(allowed_checks("daniel-okafor-cfo")) == {"invoice_po_match", "approval_threshold"}


@pytest.mark.parametrize("raw", ['["sla_status"', "sla_status", '{"checks": []}', '["nope"]',
                                 "[1]"])
def test_unparseable_or_unknown_output_is_unavailable_not_a_guess(raw):
    assert parse_output(raw, "priya-raman-support") == (None, [])


def test_valid_output_is_masked_to_persona():
    assert parse_output('["travel_policy", "sla_status"]', "priya-raman-support") == (
        ["sla_status"], ["travel_policy"])
    assert parse_output("[]", "noah-williams-assistant") == ([], [])


def test_unavailable_counts_as_wrong_and_noise_false_positives_are_measured():
    gold = [{"id": "a", "persona": "p", "checks": ["sla_status"]},
            {"id": "b", "persona": "p", "checks": []}]
    preds = [{"id": "a", "checks": None}, {"id": "b", "checks": ["sla_status"]}]
    s = score(gold, preds)
    assert s["exact_match"] == 0 and s["invalid_rate"] == 0.5
    assert s["noise_false_positive_rate"] == 1.0
    assert s["per_check"]["sla_status"]["recall"] == 0.0


def test_test_split_uses_held_out_entities_and_text_never_seen_in_train():
    splits = generate_all()
    train_text = {(r["subject"], r["body"]) for r in splits["train"]}
    assert not train_text & {(r["subject"], r["body"]) for r in splits["test"]}
    train_only = [v for k in ("vendor", "error") for v in POOLS[k][0]]
    for row in splits["test"]:
        assert not any(v in row["body"] or v in row["subject"] for v in train_only)


def test_synthetic_data_never_copies_gold_fixture_wording():
    gold = load_gold()
    synthetic = [r for split in ("train", "val", "test") for r in generate(split)]
    gold_sentences = {s.strip() for g in gold for s in g["body"].replace("\n", " ").split(".")
                      if len(s.split()) >= 6}
    for row in synthetic:
        assert row["subject"] not in {g["subject"] for g in gold}
        assert not any(s in row["body"] for s in gold_sentences)


def test_teacher_version_1_is_reproducible_and_later_versions_only_add():
    v1 = generate("train", version=1)
    assert v1 == generate("train", version=1)
    assert {r["family"] for r in v1} < {r["family"] for r in generate("train", version=2)}


def test_teacher_v3_gives_every_family_at_least_three_training_phrasings():
    assert min(len(train) for _, _, _, train, _ in families(3)) >= 3
    v2_tests = {name: test for name, _, _, _, test in families(2)}
    assert {name: test for name, _, _, _, test in families(3)} == v2_tests


def test_gold_is_every_fixture_with_its_required_checks():
    gold = load_gold()
    assert len(gold) == len(list(FIXTURES.glob("*/*.json")))
    daniel = next(r for r in gold if r["id"] == "daniel-001")
    assert daniel["checks"] == ["invoice_po_match", "approval_threshold"]


def test_gate_thresholds_are_locked(tmp_path: Path):
    assert load_gates(ROOT / "gates.json")["version"] == 2
    loosened = json.loads((ROOT / "gates.json").read_text(encoding="utf-8"))
    loosened["test"]["min_exact_match"] = 0.5
    path = tmp_path / "gates.json"
    path.write_text(json.dumps(loosened), encoding="utf-8")
    with pytest.raises(SystemExit, match="locked"):
        load_gates(path, GATES_SHA256)


def test_gate_fails_a_candidate_that_trails_the_baseline_on_gold():
    gates = load_gates(ROOT / "gates.json")
    rows = {"test": [{"id": "t", "persona": "p", "checks": ["sla_status"]},
                     {"id": "n", "persona": "p", "checks": []}],
            "gold": [{"id": "g1", "persona": "p", "checks": ["sla_status"]},
                     {"id": "g2", "persona": "p", "checks": ["sla_status"]}]}
    right = [{"id": "g1", "checks": ["sla_status"]}, {"id": "g2", "checks": ["sla_status"]}]
    good = {"test": [{"id": "t", "checks": ["sla_status"]}, {"id": "n", "checks": []}],
            "gold": right}
    worse = {"test": good["test"], "gold": [{"id": "g1", "checks": ["sla_status"]},
                                            {"id": "g2", "checks": ["sla_status",
                                                                    "refund_eligibility"]}]}
    assert evaluate(gates, rows, good, good)["passed"]
    report = evaluate(gates, rows, worse, good)
    assert not report["passed"]
    assert [c["name"] for c in report["conditions"] if not c["passed"]] == [
        "gold.exact_match_minus_baseline"]
    needed = gates["robustness"]["min_independent_runs"]
    assert evaluate_runs(gates, rows, {f"r{i}": good for i in range(needed)}, good)["passed"]
    assert not evaluate_runs(gates, rows, {f"r{i}": good for i in range(needed - 1)},
                             good)["passed"]
    mixed = {f"r{i}": good for i in range(needed - 1)} | {"unlucky": worse}
    assert not evaluate_runs(gates, rows, mixed, good)["passed"]


def test_paths_must_be_workshop_relative():
    assert workshop_path("runs/router") == ROOT / "runs" / "router"
    for bad in (str(ROOT / "runs"), "../outside"):
        with pytest.raises(ValueError):
            workshop_path(bad)
