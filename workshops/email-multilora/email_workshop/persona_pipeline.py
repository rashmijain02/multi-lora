from __future__ import annotations

import argparse
import gc
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from email_workshop.data import write_json
from email_workshop.model_profiles import model_profile_keys, resolve_model_profile
from email_workshop.persona import (
    PersonaBackend,
    evaluate_persona,
    load_persona_dataset,
    load_persona_registry,
    score_persona,
    train_persona_adapter,
    verify_persona_adapter,
)
from email_workshop.training import TrainConfig, train_config_dict

DEFAULT_PERSONA_MODEL_PROFILE = "qwen2.5-3b"


@dataclass(frozen=True)
class PersonaPipelineConfig:
    workshop_root: Path
    root: Path
    model_profile: str
    model_id: str
    model_revision: str
    target_modules: tuple[str, ...]
    device: str = "cuda"
    seed: int = 2026
    max_length: int = 1024
    rank: int = 8
    epochs: float = 1.0
    learning_rate: float = 2e-4
    batch_size: int = 1
    gradient_accumulation: int = 8
    max_steps: int = -1
    sample_limit: int | None = None
    evaluation_limit: int = 8
    clients: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.device not in ("cpu", "cuda"):
            raise ValueError("device must be cpu or cuda.")
        if self.max_length < 512:
            raise ValueError("max_length must be at least 512.")
        if min(
            self.rank,
            self.epochs,
            self.learning_rate,
            self.batch_size,
            self.gradient_accumulation,
            self.evaluation_limit,
        ) <= 0:
            raise ValueError("Training and evaluation settings must be positive.")
        if self.max_steps == 0 or self.max_steps < -1:
            raise ValueError("max_steps must be -1 or positive.")
        if self.sample_limit is not None and self.sample_limit < 1:
            raise ValueError("sample_limit must be positive.")


def emit(event: str, **details: Any) -> None:
    print(json.dumps({"event": event, **details}, ensure_ascii=False), flush=True)


def public_config(config: PersonaPipelineConfig) -> dict[str, Any]:
    value = asdict(config)
    value["workshop_root"] = str(config.workshop_root)
    value["root"] = str(config.root)
    value["target_modules"] = list(config.target_modules)
    value["clients"] = list(config.clients)
    return value


def _train_config(config: PersonaPipelineConfig) -> TrainConfig:
    return TrainConfig(
        model_profile=config.model_profile,
        model_id=config.model_id,
        model_revision=config.model_revision,
        target_modules=config.target_modules,
        seed=config.seed,
        max_length=config.max_length,
        rank=config.rank,
        epochs=config.epochs,
        learning_rate=config.learning_rate,
        batch_size=config.batch_size,
        gradient_accumulation=config.gradient_accumulation,
        max_steps=config.max_steps,
        sample_limit=config.sample_limit,
        device=config.device,
    )


def _status_path(config: PersonaPipelineConfig) -> Path:
    return config.root / "persona_pipeline" / "status.json"


def _write_status(
    config: PersonaPipelineConfig,
    states: dict[str, dict[str, Any]],
    state: str,
) -> None:
    write_json(
        _status_path(config),
        {
            "state": state,
            "updated_at": datetime.now(UTC).isoformat(),
            "config": public_config(config),
            "clients": states,
        },
    )


def _release_backend(backend: PersonaBackend) -> None:
    del backend.model
    del backend
    gc.collect()
    if config_device_cuda_available():
        import torch

        torch.cuda.empty_cache()


def config_device_cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def run_persona_pipeline(config: PersonaPipelineConfig) -> dict[str, Any]:
    registry = load_persona_registry(config.workshop_root)
    clients = config.clients or tuple(registry)
    unknown = set(clients) - set(registry)
    if unknown:
        raise ValueError(f"Unknown clients: {sorted(unknown)}")
    if len(set(clients)) != len(clients):
        raise ValueError("Client list contains duplicates.")

    train_config = _train_config(config)
    expected_train_config = train_config_dict(train_config)
    states: dict[str, dict[str, Any]] = {
        client_id: {"state": "pending"} for client_id in clients
    }
    _write_status(config, states, "running")
    emit("persona_pipeline_started", config=public_config(config))

    for position, client_id in enumerate(clients, start=1):
        spec = registry[client_id]
        states[client_id] = {"state": "validating", "position": position}
        _write_status(config, states, "running")
        splits, _, _, data_manifest = load_persona_dataset(
            config.workshop_root, client_id
        )
        adapter_path = config.root / "persona_adapters" / spec["adapter"]
        manifest_path = adapter_path / "manifest.json"

        reused = False
        if manifest_path.exists():
            manifest = verify_persona_adapter(
                config.root, config.workshop_root, client_id
            )
            if manifest["config"] != expected_train_config:
                raise ValueError(
                    f"Existing adapter configuration differs for {client_id}; "
                    "use a new pipeline root."
                )
            reused = True
            emit("persona_adapter_reused", client_id=client_id, adapter=spec["adapter"])
        elif adapter_path.exists():
            raise ValueError(
                f"Incomplete adapter directory exists for {client_id}: {adapter_path}"
            )
        else:
            states[client_id] = {"state": "training", "position": position}
            _write_status(config, states, "running")
            emit("persona_training_started", client_id=client_id, adapter=spec["adapter"])
            manifest = train_persona_adapter(
                config.root,
                config.workshop_root,
                client_id,
                train_config,
            )
            emit(
                "persona_training_completed",
                client_id=client_id,
                adapter=spec["adapter"],
                elapsed_seconds=manifest["elapsed_seconds"],
                train_loss=manifest["metrics"].get("train_loss"),
            )

        states[client_id] = {"state": "evaluating", "position": position}
        _write_status(config, states, "running")
        backend = PersonaBackend(
            config.root, config.workshop_root, client_id, device=config.device
        )
        evaluation: dict[str, dict[str, float | int]] = {}
        try:
            rows = splits["validation"][: config.evaluation_limit]
            for mode in ("base", "adapted"):
                output = (
                    config.root
                    / "persona_evaluation"
                    / spec["adapter"]
                    / f"validation-{mode}.json"
                )
                predictions = evaluate_persona(
                    rows, backend, mode, output, "validation"
                )
                evaluation[mode] = score_persona(predictions)
        finally:
            _release_backend(backend)

        states[client_id] = {
            "state": "completed",
            "position": position,
            "reused": reused,
            "adapter": spec["adapter"],
            "purpose": manifest["purpose"],
            "data_sha256": data_manifest["dataset_sha256"],
            "train_rows": manifest["train_rows"],
            "validation_rows_evaluated": config.evaluation_limit,
            "evaluation": evaluation,
        }
        _write_status(config, states, "running")
        emit(
            "persona_completed",
            client_id=client_id,
            adapter=spec["adapter"],
            reused=reused,
            evaluation=evaluation,
        )

    result = {
        "state": "completed",
        "completed_at": datetime.now(UTC).isoformat(),
        "config": public_config(config),
        "clients": states,
    }
    write_json(config.root / "persona_pipeline" / "result.json", result)
    _write_status(config, states, "completed")
    emit("persona_pipeline_completed", clients=len(clients), root=str(config.root))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and validate one LoRA response adapter per registered client."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("artifacts/persona-qwen2.5-3b-full"),
    )
    parser.add_argument("--workshop-root", type=Path, default=Path("."))
    parser.add_argument(
        "--model-profile",
        choices=model_profile_keys(),
        default=DEFAULT_PERSONA_MODEL_PROFILE,
    )
    parser.add_argument("--model-id")
    parser.add_argument("--model-revision")
    parser.add_argument("--target-modules", nargs="+")
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--sample-limit", type=int)
    parser.add_argument("--evaluation-limit", type=int, default=8)
    parser.add_argument("--clients", nargs="+")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Execute training. Without --run, print the resolved plan only.",
    )
    return parser


def resolved_config(args: argparse.Namespace) -> PersonaPipelineConfig:
    model = resolve_model_profile(
        args.model_profile,
        model_id=args.model_id,
        revision=args.model_revision,
        target_modules=tuple(args.target_modules) if args.target_modules else None,
    )
    workshop_root = args.workshop_root.resolve()
    registry = load_persona_registry(workshop_root)
    return PersonaPipelineConfig(
        workshop_root=workshop_root,
        root=(workshop_root / args.root).resolve()
        if not args.root.is_absolute()
        else args.root.resolve(),
        model_profile=model.key,
        model_id=model.model_id,
        model_revision=model.revision,
        target_modules=model.target_modules,
        device=args.device,
        seed=args.seed,
        max_length=args.max_length,
        rank=args.rank,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        batch_size=args.batch_size,
        gradient_accumulation=args.gradient_accumulation,
        max_steps=args.max_steps,
        sample_limit=args.sample_limit,
        evaluation_limit=args.evaluation_limit,
        clients=tuple(args.clients) if args.clients else tuple(registry),
    )


def main() -> None:
    args = build_parser().parse_args()
    config = resolved_config(args)
    print(json.dumps(public_config(config), indent=2))
    if not args.run:
        print("Plan only. Add --run to train sequentially.")
        return
    run_persona_pipeline(config)


if __name__ == "__main__":
    main()
