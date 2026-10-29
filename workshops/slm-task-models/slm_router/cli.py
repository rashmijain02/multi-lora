"""Router CLI. Run from ``workshops/slm-task-models``; every path is relative to that folder.

    uv run python -m slm_router data                      # synthetic splits + sealed gold set
    uv run python -m slm_router k0                        # lexical baseline + predictions
    uv run --group train python -m slm_router train       # LoRA student on the GPU
    uv run --group train python -m slm_router predict     # student predictions, one at a time
    uv run python -m slm_router gate --candidate runs/router/student --baseline runs/router/k0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from slm_router.data import ROOT, load_gold, read_jsonl, sha256, workshop_path, write_jsonl

SPLIT_FILES = ("train", "val", "test", "gold")


def load_data(data_dir: Path) -> tuple[dict[str, list[dict]], str]:
    manifest = data_dir / "manifest.json"
    if not manifest.exists():
        raise SystemExit("No dataset yet: run `python -m slm_router data` first.")
    recorded = json.loads(manifest.read_text(encoding="utf-8"))["sha256"]
    splits = {}
    for name in SPLIT_FILES:
        path = data_dir / f"{name}.jsonl"
        if sha256(path) != recorded[name]:
            raise SystemExit(f"{name}.jsonl no longer matches manifest.json; rebuild the data.")
        splits[name] = read_jsonl(path)
    return splits, sha256(manifest)


def write_predictions(out_dir: Path, predictions: dict[str, list[dict]], info: dict) -> None:
    for name, rows in predictions.items():
        write_jsonl(out_dir / f"predictions_{name}.jsonl", rows)
    (out_dir / "run_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


def cmd_data(args) -> int:
    from collections import Counter

    from slm_router.synth import generate_all

    out = workshop_path(args.out)
    splits = generate_all(args.seed, args.teacher_version)
    splits["gold"] = load_gold()
    for name in SPLIT_FILES:
        write_jsonl(out / f"{name}.jsonl", splits[name])
    manifest = {
        "seed": args.seed,
        "teacher_version": args.teacher_version,
        "rows": {name: len(splits[name]) for name in SPLIT_FILES},
        "label_sets": {name: dict(Counter("+".join(r["checks"]) or "[]" for r in splits[name]))
                       for name in SPLIT_FILES},
        "sha256": {name: sha256(out / f"{name}.jsonl") for name in SPLIT_FILES},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest["rows"]), f"-> {out.relative_to(ROOT).as_posix()}")
    return 0


def cmd_k0(args) -> int:
    from slm_router.k0 import fit_predict
    from slm_router.metrics import score

    splits, manifest = load_data(workshop_path(args.data))
    predictions, info = fit_predict(splits, args.seed)
    info["data_manifest_sha256"] = manifest
    out = workshop_path(args.out)
    write_predictions(out, predictions, info)
    for name in ("val", "test", "gold"):
        s = score(splits[name], predictions[name])
        print(f"K0 {name:5s} exact {s['exact_match']:.3f}  micro-F1 {s['micro_f1']:.3f}  "
              f"noise-FP {s['noise_false_positive_rate']}")
    return 0


def cmd_train(args) -> int:
    from dataclasses import replace

    from slm_router.student import StudentConfig, train

    splits, manifest = load_data(workshop_path(args.data))
    config = StudentConfig()
    if args.epochs is not None:
        config = replace(config, epochs=args.epochs)
    if args.seed is not None:
        config = replace(config, seed=args.seed)
    out = workshop_path(args.out)
    info = train(splits["train"], out, config)
    info["data_manifest_sha256"] = manifest
    (out / "train_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"trained {info['optimizer_steps']} steps in {info['train_seconds']} s, peak "
          f"{info['peak_gpu_memory_gb']} GB, loss {info['loss_first_10_mean']:.3f} -> "
          f"{info['loss_last_10_mean']:.3f}")
    return 0


def cmd_predict(args) -> int:
    from slm_router.metrics import score
    from slm_router.student import Student

    splits, manifest = load_data(workshop_path(args.data))
    model_dir = workshop_path(args.model)
    student = Student(model_dir / "adapter")
    student.route(splits["val"][0])  # warm-up so the first timed request is not a cold start
    predictions = {name: [student.route(r) for r in splits[name]]
                   for name in ("val", "test", "gold")}
    write_predictions(model_dir, predictions, {"model": "qwen2.5-0.5b-lora-student",
                                               "data_manifest_sha256": manifest})
    for name in ("val", "test", "gold"):
        s = score(splits[name], predictions[name])
        print(f"student {name:5s} exact {s['exact_match']:.3f}  invalid {s['invalid_rate']:.3f}"
              f"  p50 {s['latency_ms_p50']} ms")
    return 0


def _load_predictions(run_dir: Path, manifest: str) -> dict[str, list[dict]]:
    info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    if info.get("data_manifest_sha256") != manifest:
        raise SystemExit(f"{run_dir.name}: predictions were made on a different dataset.")
    return {name: read_jsonl(run_dir / f"predictions_{name}.jsonl")
            for name in ("val", "test", "gold")}


def cmd_gate(args) -> int:
    from slm_router.gate import evaluate_runs, load_gates

    gates_path = ROOT / "gates.json"
    gates = load_gates(gates_path)
    gold, manifest = load_data(workshop_path(args.data))
    if len(set(args.candidate)) != len(args.candidate):
        raise SystemExit("each --candidate must be a different run directory")
    candidates = {c: _load_predictions(workshop_path(c), manifest) for c in args.candidate}
    baseline = _load_predictions(workshop_path(args.baseline), manifest) if args.baseline else None
    report = evaluate_runs(gates, gold, candidates, baseline)
    report["gates_sha256"] = sha256(gates_path)
    report["gates_version"] = gates["version"]
    report["baseline"] = args.baseline
    report["seeds"] = {}
    for c in args.candidate:
        info = workshop_path(c) / "train_info.json"
        if info.exists():
            report["seeds"][c] = json.loads(info.read_text(encoding="utf-8"))["config"]["seed"]
    out = workshop_path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, run in report["runs"].items():
        print(f"== {name}")
        for c in run["conditions"]:
            value = "n/a" if c["value"] is None else f"{c['value']:.3f}"
            print(f"{'PASS' if c['passed'] else 'FAIL'}  {c['name']:38s} {value} "
                  f"{c['direction']} {c['threshold']}")
        print("run PASSED" if run["passed"] else "run FAILED")
    count = report["run_count_condition"]
    print(f"{'PASS' if count['passed'] else 'FAIL'}  independent runs {count['value']} >= "
          f"{count['threshold']}")
    print("GATE PASSED" if report["passed"] else "GATE FAILED")
    return 0 if report["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slm_router", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("data", help="build synthetic splits and the sealed gold set")
    p.add_argument("--out", default="runs/router/data")
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--teacher-version", type=int, default=3, choices=(1, 2, 3),
                   help="1 = round-1 families; 2 = adds round-2 families; 3 = >=3 train phrasings")
    p.set_defaults(func=cmd_data)
    p = sub.add_parser("k0", help="fit the lexical baseline and write predictions")
    p.add_argument("--data", default="runs/router/data")
    p.add_argument("--out", default="runs/router/k0")
    p.add_argument("--seed", type=int, default=2026)
    p.set_defaults(func=cmd_k0)
    p = sub.add_parser("train", help="LoRA-train the student (needs --group train and a GPU)")
    p.add_argument("--data", default="runs/router/data")
    p.add_argument("--out", default="runs/router/student")
    p.add_argument("--epochs", type=int)
    p.add_argument("--seed", type=int)
    p.set_defaults(func=cmd_train)
    p = sub.add_parser("predict", help="route val/test/gold one request at a time")
    p.add_argument("--data", default="runs/router/data")
    p.add_argument("--model", default="runs/router/student")
    p.set_defaults(func=cmd_predict)
    p = sub.add_parser("gate", help="apply the locked parity gate")
    p.add_argument("--data", default="runs/router/data")
    p.add_argument("--candidate", required=True, action="append",
                   help="a run directory; repeat once per independent training run")
    p.add_argument("--baseline")
    p.add_argument("--report", default="runs/router/gate_report.json")
    p.set_defaults(func=cmd_gate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
