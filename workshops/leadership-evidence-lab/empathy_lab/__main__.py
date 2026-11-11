"""Small manual CLI for validation, baseline evaluation, inference, and LoRA training."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .baseline import fit_baseline, predict_baseline
from .config import ModelConfig
from .data import load_dataset, split_records
from .evaluation import evaluate
from .modeling import predict, train


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m empathy_lab")
    parser.add_argument(
        "--data",
        default=None,
        help="JSONL dataset path (defaults to the bundled fictional examples)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "experiment", help="configurable three-task preparation/training/evaluation"
    )
    commands.add_parser("validate", help="validate the dataset and report split sizes")

    baseline = commands.add_parser("baseline", help="fit and evaluate train-only lexical heads")
    baseline.add_argument("--split", choices=("validation", "test"), default="test")

    inference = commands.add_parser("infer", help="run deterministic HF model inference")
    inference.add_argument("--config", required=True)
    inference.add_argument("--split", choices=("validation", "test"), default="test")
    inference.add_argument("--adapter")
    inference.add_argument("--report", default="artifacts/predictions.json")

    training = commands.add_parser("train", help="manually run train/validation LoRA SFT")
    training.add_argument("--config", required=True)
    training.add_argument("--output", default="artifacts/lora-adapter")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "experiment":
        from .experiment import main as experiment_main

        return experiment_main(arguments[1:])
    args = _parser().parse_args(arguments)
    records = load_dataset(args.data) if args.data else load_dataset()
    splits = split_records(records)

    if args.command == "validate":
        print(json.dumps({split: len(items) for split, items in splits.items()}, indent=2))
        return 0
    if args.command == "baseline":
        model = fit_baseline(splits["train"])
        predictions = predict_baseline(model, splits[args.split])
        report = evaluate(splits[args.split], predictions)
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    if args.command == "infer":
        config = ModelConfig.from_json(args.config)
        predictions = predict(
            config,
            splits[args.split],
            adapter_path=args.adapter,
            report_path=args.report,
        )
        report = evaluate(splits[args.split], predictions)
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    if args.command == "train":
        trainer = train(
            ModelConfig.from_json(args.config),
            splits["train"],
            splits["validation"],
            args.output,
        )
        print(
            json.dumps({"output_dir": str(Path(args.output)), "train_result": str(trainer.state)})
        )
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
