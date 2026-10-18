from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from email_workshop.data import ADAPTERS, load_splits, prepare, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-label email Multi-LoRA workshop")
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/run-2026"))
    commands = parser.add_subparsers(dest="command", required=True)
    data_parser = commands.add_parser("prepare")
    data_parser.add_argument("--seed", type=int, default=2026)
    router_parser = commands.add_parser("router")
    router_parser.add_argument("--target-recall", type=float, default=0.95)
    training = commands.add_parser("train")
    training.add_argument("--adapter", choices=(*ADAPTERS, "all"), default="all")
    training.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    training.add_argument("--epochs", type=float, default=2.0)
    training.add_argument("--max-steps", type=int, default=-1)
    training.add_argument("--sample-limit", type=int)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--backend", choices=("peft", "vllm"), default="peft")
    evaluation.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    evaluation.add_argument("--split", choices=("validation", "test"), default="validation")
    evaluation.add_argument("--limit", type=int)
    evaluation.add_argument("--allow-smoke", action="store_true")
    serving = commands.add_parser("vllm-command")
    serving.add_argument("--linux-run-root", required=True)
    args = parser.parse_args()
    root = args.artifacts.resolve()
    if args.command == "prepare":
        print(json.dumps(prepare(root, args.seed), indent=2))
    elif args.command == "router":
        from email_workshop.evaluation import lexical_predictions, score
        from email_workshop.routing import fit_router

        router, metadata = fit_router(root, args.target_recall)
        splits, _ = load_splits(root)
        summary, per_label = score(lexical_predictions(splits["validation"], router))
        write_json(
            root / "router" / "validation_metrics.json",
            {
                "summary": summary,
                "per_label": per_label,
            },
        )
        print(json.dumps({"router": metadata, "validation": summary}, indent=2))
    elif args.command == "train":
        from email_workshop.training import TrainConfig, train_adapter

        config = TrainConfig(
            device=args.device,
            epochs=args.epochs,
            max_steps=args.max_steps,
            sample_limit=args.sample_limit,
        )
        for name in ADAPTERS if args.adapter == "all" else [args.adapter]:
            manifest = train_adapter(root, name, config)
            print(json.dumps({"adapter": name, "metrics": manifest["metrics"]}, indent=2))
    elif args.command == "vllm-command":
        from email_workshop.serving import vllm_command

        print(shlex.join(vllm_command(root, args.linux_run_root)))
    else:
        from email_workshop.evaluation import STRATEGIES, evaluate, score
        from email_workshop.routing import fit_router
        from email_workshop.serving import VllmBackend
        from email_workshop.training import LocalBackend, verify_adapters

        manifests = verify_adapters(root)
        if not args.allow_smoke and any(item["purpose"] == "smoke" for item in manifests.values()):
            raise ValueError(
                "Smoke adapters cannot support quality claims; pass --allow-smoke explicitly."
            )
        splits, _ = load_splits(root)
        rows = splits[args.split]
        if args.limit is not None:
            if not 0 < args.limit <= len(rows):
                raise ValueError("--limit must be between 1 and the split size.")
            rows = rows[: args.limit]
        router, metadata = fit_router(root)
        backend = LocalBackend(root, args.device) if args.backend == "peft" else VllmBackend(root)
        comparison = {}
        for strategy in STRATEGIES:
            output = root / "evaluation" / f"{args.backend}-{args.split}-{strategy}.json"
            predictions = evaluate(rows, backend, router, metadata, strategy, output, args.split)
            summary, per_label = score(predictions)
            comparison[strategy] = summary
            write_json(
                output.with_suffix(".metrics.json"), {"summary": summary, "per_label": per_label}
            )
        print(json.dumps(comparison, indent=2))


if __name__ == "__main__":
    main()
