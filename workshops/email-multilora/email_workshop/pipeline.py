from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from email_workshop.data import ADAPTERS, load_splits, prepare, write_json
from email_workshop.evaluation import STRATEGIES, evaluate, lexical_predictions, score
from email_workshop.modeling import LocalBackend, TrainConfig, train_adapter, verify_adapters
from email_workshop.routing import fit_router

STAGES = ("prepare", "router", "train", "evaluate")


@dataclass(frozen=True)
class PipelineConfig:
    root: Path
    profile: str
    device: str
    seed: int = 2026
    target_recall: float = 0.95
    epochs: float = 2.0
    max_steps: int = -1
    sample_limit: int | None = None
    evaluation_limit: int | None = None
    include_test: bool = False
    source: Path | None = None

    def __post_init__(self) -> None:
        if self.profile not in ("smoke", "full"):
            raise ValueError("profile must be smoke or full.")
        if self.device not in ("cpu", "cuda"):
            raise ValueError("device must be cpu or cuda.")
        if not 0 < self.target_recall <= 1:
            raise ValueError("target_recall must be in (0, 1].")
        if self.epochs <= 0:
            raise ValueError("epochs must be positive.")
        if self.max_steps == 0 or self.max_steps < -1:
            raise ValueError("max_steps must be -1 or positive.")
        if self.sample_limit is not None and self.sample_limit < 1:
            raise ValueError("sample_limit must be positive.")
        if self.evaluation_limit is not None and self.evaluation_limit < 1:
            raise ValueError("evaluation_limit must be positive.")
        if self.profile == "full" and (
            self.max_steps != -1
            or self.sample_limit is not None
            or self.evaluation_limit is not None
        ):
            raise ValueError("full profile cannot use smoke limits.")


def resolved_config(args: argparse.Namespace) -> PipelineConfig:
    profile = args.profile
    root = args.artifacts or Path(f"artifacts/pipeline-{profile}")
    return PipelineConfig(
        root=root.resolve(),
        profile=profile,
        device=args.device or ("cpu" if profile == "smoke" else "cuda"),
        seed=args.seed,
        target_recall=args.target_recall,
        epochs=args.epochs,
        max_steps=args.max_steps if args.max_steps is not None else (2 if profile == "smoke" else -1),
        sample_limit=(
            args.sample_limit if args.sample_limit is not None else (16 if profile == "smoke" else None)
        ),
        evaluation_limit=(
            args.evaluation_limit
            if args.evaluation_limit is not None
            else (4 if profile == "smoke" else None)
        ),
        include_test=args.include_test,
        source=args.source.resolve() if args.source else None,
    )


def public_config(config: PipelineConfig) -> dict[str, Any]:
    value = asdict(config)
    value["root"] = str(config.root)
    value["source"] = str(config.source) if config.source else None
    return value


def emit(event: str, **details: Any) -> None:
    print(json.dumps({"event": event, **details}, ensure_ascii=False), file=sys.stderr, flush=True)


def update_status(config: PipelineConfig, stages: dict[str, dict[str, Any]]) -> None:
    write_json(
        config.root / "pipeline" / "status.json",
        {
            "profile": config.profile,
            "device": config.device,
            "updated_at": datetime.now(UTC).isoformat(),
            "stages": stages,
        },
    )


def run_pipeline(config: PipelineConfig) -> dict[str, Any]:
    stages: dict[str, dict[str, Any]] = {}

    def complete(name: str, *, reused: bool = False, **details: Any) -> None:
        stages[name] = {"state": "completed", "reused": reused, **details}
        update_status(config, stages)
        emit("stage_completed", stage=name, reused=reused, **details)

    emit("pipeline_started", **public_config(config))

    emit("stage_started", stage="prepare")
    if (config.root / "data" / "manifest.json").exists():
        splits, manifest = load_splits(config.root)
        if manifest["seed"] != config.seed:
            raise ValueError("Existing dataset seed differs from the pipeline plan; use a new root.")
        if config.source is not None and manifest["dataset"] != "local":
            raise ValueError("Existing data did not come from the requested local source.")
        if config.source is not None and hashlib.sha256(config.source.read_bytes()).hexdigest() != manifest[
            "source_sha256"
        ]:
            raise ValueError("Existing data differs from the requested local source; use a new root.")
        complete(
            "prepare",
            reused=True,
            rows={name: len(rows) for name, rows in splits.items()},
            dataset=manifest["dataset"],
        )
    else:
        manifest = prepare(config.root, config.seed, config.source)
        complete(
            "prepare",
            rows={name: item["rows"] for name, item in manifest["splits"].items()},
            dataset=manifest["dataset"],
        )

    emit("stage_started", stage="router")
    router_metadata_path = config.root / "router" / "metadata.json"
    router, router_metadata = fit_router(
        config.root, None if router_metadata_path.exists() else config.target_recall
    )
    if router_metadata["target_recall"] != config.target_recall:
        raise ValueError("Existing router target differs from the pipeline plan; use a new root.")
    splits, _ = load_splits(config.root)
    lexical_summary, lexical_per_label = score(
        lexical_predictions(splits["validation"], router)
    )
    write_json(
        config.root / "router" / "validation_metrics.json",
        {"summary": lexical_summary, "per_label": lexical_per_label},
    )
    complete(
        "router",
        targetRecall=router_metadata["target_recall"],
        validationDomainRecall=router_metadata["validation_domain_recall"],
        lexicalMicroF1=lexical_summary["micro_f1"],
    )

    emit("stage_started", stage="train")
    train_config = TrainConfig(
        seed=config.seed,
        device=config.device,
        epochs=config.epochs,
        max_steps=config.max_steps,
        sample_limit=config.sample_limit,
    )
    trained: list[str] = []
    reused_adapters: list[str] = []
    for adapter in ADAPTERS:
        destination = config.root / "adapters" / adapter
        if destination.exists():
            if not (destination / "manifest.json").is_file():
                raise RuntimeError(
                    f"Incomplete adapter directory exists for {adapter}; use a new artifact root."
                )
            reused_adapters.append(adapter)
            emit("adapter_reused", adapter=adapter)
            continue
        emit("adapter_started", adapter=adapter)
        train_adapter(config.root, adapter, train_config)
        trained.append(adapter)
        emit("adapter_completed", adapter=adapter)
    manifests = verify_adapters(config.root)
    expected_training_config = asdict(train_config)
    if any(item["config"] != expected_training_config for item in manifests.values()):
        raise ValueError("Existing adapter configuration differs from the pipeline plan.")
    purposes = sorted({item["purpose"] for item in manifests.values()})
    complete(
        "train",
        reused=not trained,
        trainedAdapters=trained,
        reusedAdapters=reused_adapters,
        purposes=purposes,
    )

    emit("stage_started", stage="evaluate")
    backend = LocalBackend(config.root, config.device)
    evaluation: dict[str, dict[str, Any]] = {}
    split_names = ["validation"]
    if config.include_test:
        split_names.append("test")
    for split_name in split_names:
        rows = splits[split_name]
        if config.evaluation_limit is not None:
            rows = rows[: config.evaluation_limit]
        comparison: dict[str, Any] = {}
        for strategy in STRATEGIES:
            emit("evaluation_started", split=split_name, strategy=strategy, rows=len(rows))
            output = (
                config.root / "evaluation" / f"peft-{split_name}-{strategy}.json"
            )
            predictions = evaluate(
                rows,
                backend,
                router,
                router_metadata,
                strategy,
                output,
                split_name,
            )
            summary, per_label = score(predictions)
            write_json(
                output.with_suffix(".metrics.json"),
                {"summary": summary, "per_label": per_label},
            )
            comparison[strategy] = summary
            emit("evaluation_completed", split=split_name, strategy=strategy)
        evaluation[split_name] = comparison
    complete(
        "evaluate",
        splits=list(evaluation),
        rowsPerSplit={
            name: next(iter(result.values()))["rows"] for name, result in evaluation.items()
        },
    )

    result = {
        "status": "completed",
        "profile": config.profile,
        "device": config.device,
        "artifacts": str(config.root),
        "stages": stages,
        "evaluation": evaluation,
    }
    write_json(config.root / "pipeline" / "result.json", result)
    emit("pipeline_completed", artifacts=str(config.root))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the email Multi-LoRA workshop as one staged, resumable pipeline."
    )
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--profile", choices=("smoke", "full"), required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"))
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--target-recall", type=float, default=0.95)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--sample-limit", type=int)
    parser.add_argument("--evaluation-limit", type=int)
    parser.add_argument(
        "--include-test",
        action="store_true",
        help="Evaluate the frozen test split after validation (use only after design freeze).",
    )
    parser.add_argument(
        "--source",
        type=Path,
        help="Optional local dataset JSON; otherwise download the pinned public dataset.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute all stages. Without this flag, print the resolved plan only.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = resolved_config(args)
    if not args.run:
        print(
            json.dumps(
                {
                    "mode": "plan only; no downloads, training, evaluation, or cloud calls",
                    "stages": STAGES,
                    "config": public_config(config),
                    "run": "Add --run after reviewing this plan.",
                },
                indent=2,
            )
        )
        return
    print(json.dumps(run_pipeline(config), indent=2))


if __name__ == "__main__":
    main()
