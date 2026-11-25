"""Run the local prompt-baseline vs. QLoRA SFT email-reply experiment."""

import argparse
import gc
import hashlib
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sft.trainer import fit, load_model, runtime
from util.data import load_pairs, private_output, save_split, split_pairs
from util.evaluation import (
    build_comparison_identity,
    evaluate_model,
    format_samples,
    load_saved_stage_summary,
    prepare_evaluation,
    sample_drafts,
    save_baseline_run,
)
from util.monitoring import (
    plot_losses,
    plot_sft_diagnostics,
    plot_stage_comparison,
    read_metrics,
    save_figure,
)
from util.paths import (
    DEFAULT_OUTPUT_ROOT,
    display_path,
    prepare_output_root,
    resolve_input_dir,
)
from util.prompts import INSTRUCTION, Hardware, ModelProfile, format_model_ref


@dataclass(frozen=True)
class Experiment:
    run_dir: Path
    baseline_run_dir: Path
    metrics_file: Path
    loss_plot: Path
    diagnostics_plot: Path
    comparison_plot: Path
    samples_file: Path | None
    baseline: dict
    fine_tuned: dict
    comparison_identity: dict
    history: list[dict]
    samples: list[dict]
    peak_allocated_mib: float
    peak_reserved_mib: float


def _derive_digests(splits: dict, dataset: dict | None, split_sha256: str | None, seed: int) -> tuple[str, str]:
    canonical_splits = {
        name: [
            {"line": p.line, "conversation": p.conversation, "reply": p.reply}
            for p in entries
        ]
        for name, entries in sorted(splits.items())
    }
    raw_bytes = json.dumps(canonical_splits, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ds_hash = (
        str(dataset["source_sha256"])
        if isinstance(dataset, dict) and isinstance(dataset.get("source_sha256"), str)
        else hashlib.sha256(raw_bytes).hexdigest()
    )
    if split_sha256:
        sp_hash = split_sha256
    else:
        manifest = {
            "version": 1,
            "source_sha256": ds_hash,
            "seed": seed,
            "splits": {name: [p.line for p in entries] for name, entries in splits.items()},
        }
        sp_hash = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    return ds_hash, sp_hash


def public_summary(
    result: Experiment,
    profile: ModelProfile,
    hardware: Hardware,
    fit_sets: dict,
    *,
    smoke: bool,
    seed: int,
    eval_steps: int | None = None,
    input_dir: Path | None = None,
    output_root: Path | None = None,
    split_manifest: Path | None = None,
    dataset: dict | None = None,
) -> dict:
    summary: dict[str, object] = {
        "stage": "sft",
        "smoke": smoke,
        "seed": seed,
        "eval_steps": eval_steps,
        "instruction": INSTRUCTION,
        "note": "reference_token_loss measures fit to the archived reply, not factual correctness.",
        "input_dir": display_path(input_dir) if input_dir is not None else None,
        "output_root": display_path(output_root) if output_root is not None else None,
        "split_manifest": display_path(split_manifest) if split_manifest is not None else None,
        "baseline_run": display_path(result.baseline_run_dir),
        "run_dir": display_path(result.run_dir),
        "metrics_file": display_path(result.metrics_file),
        "loss_plot": display_path(result.loss_plot),
        "training_metrics_plot": display_path(result.diagnostics_plot),
        "comparison_plot": display_path(result.comparison_plot),
        "samples_file": display_path(result.samples_file) if result.samples_file is not None else None,
        "model": asdict(profile),
        "hardware": asdict(hardware),
    }
    if dataset is not None:
        summary["dataset"] = dataset
    summary["comparison_identity"] = result.comparison_identity
    summary.update({
        "fit": {
            name: {
                "eligible": sum(case.reference is not None for case in cases),
                "over_budget": sum(case.reference is None for case in cases),
                "truncated_inputs": sum(case.prompt.truncated for case in cases),
            }
            for name, cases in fit_sets.items()
        },
        "baseline": result.baseline,
        "fine_tuned": result.fine_tuned,
        "history": result.history,
        "peak_allocated_mib": result.peak_allocated_mib,
        "peak_reserved_mib": result.peak_reserved_mib,
    })
    return summary


def run(
    splits: dict,
    profile: ModelProfile,
    hardware: Hardware,
    *,
    smoke: bool = False,
    show_private: bool = False,
    sample_count: int = 3,
    seed: int = 42,
    eval_steps: int | None = None,
    input_dir: Path | None = None,
    output_root: Path | None = None,
    split_manifest: Path | None = None,
    split_sha256: str | None = None,
    baseline_run: str | Path | None = None,
    dataset: dict | None = None,
    log: Callable[[str], None] | None = None,
) -> Experiment:
    if sample_count < 1:
        raise ValueError("Sample count must be positive.")
    if eval_steps is not None and eval_steps < 1:
        raise ValueError("--eval-steps must be a positive integer.")
    notify = log or (lambda _: None)
    torch, _ = runtime()
    if smoke:
        hardware = replace(
            hardware,
            completion_tokens=min(hardware.completion_tokens, 64),
            accumulation=1,
        )
    torch.cuda.reset_peak_memory_stats()
    cap = {"train": 4, "validation": 2, "holdout": 2}
    sft_root = private_output(output_root)
    effective_output_root = (
        output_root
        if output_root is not None
        else (DEFAULT_OUTPUT_ROOT if sft_root == DEFAULT_OUTPUT_ROOT / "sft" else sft_root)
    )
    run_path = sft_root / f"{'smoke' if smoke else 'run'}-{uuid.uuid4().hex[:12]}"

    def select(tokenizer, name: str):
        cases = prepare_evaluation(splits[name], tokenizer, profile, hardware)
        if not smoke:
            return cases
        return [case for case in cases if case.reference is not None][: cap[name]]

    notify(f"Loading base model {format_model_ref(profile.model_id, profile.revision)}...")
    model, tokenizer = load_model(profile, hardware)
    heldout = select(tokenizer, "holdout")
    if not heldout:
        raise ValueError("No holdout example available for this run.")

    ds_hash, sp_hash = _derive_digests(splits, dataset, split_sha256, seed)
    comparison_identity = build_comparison_identity(
        dataset_sha256=ds_hash,
        split_sha256=sp_hash,
        holdout_lines=[case.pair.line for case in heldout],
        profile=profile,
        hardware=hardware,
    )

    if baseline_run is not None:
        notify(f"Validating and reusing saved baseline comparison from {baseline_run}...")
        baseline_run_dir, saved_base = load_saved_stage_summary(
            baseline_run,
            comparison_identity,
            label="baseline",
            expected_stage="baseline",
        )
        raw_eval = saved_base.get("evaluation") or saved_base.get("baseline")
        if type(raw_eval) is not dict:
            raise ValueError("Saved baseline summary is missing evaluation metrics.")
        baseline = dict(raw_eval)
        if show_private:
            _, baseline_drafts = evaluate_model(model, tokenizer, heldout, profile, hardware)
        else:
            baseline_drafts = [None] * len(heldout)
    else:
        notify(f"Evaluating prompt-only baseline on {len(heldout)} holdout example(s)...")
        baseline, baseline_drafts = evaluate_model(model, tokenizer, heldout, profile, hardware)
        baseline_run_dir, _ = save_baseline_run(
            effective_output_root,
            evaluation=baseline,
            comparison_identity=comparison_identity,
            profile=profile,
            hardware=hardware,
            heldout=heldout,
            drafts=baseline_drafts,
            smoke=smoke,
            show_private=show_private,
            sample_count=sample_count,
            seed=seed,
            input_dir=input_dir,
            dataset=dataset,
        )

    fit_sets = {name: select(tokenizer, name) for name in ("train", "validation")}
    train_rows = [case.reference for case in fit_sets["train"] if case.reference is not None]
    val_rows = [case.reference for case in fit_sets["validation"] if case.reference is not None]
    notify(f"Training QLoRA adapter ({len(train_rows)} train, {len(val_rows)} validation eligible)...")
    adapter, history = fit(
        model,
        tokenizer,
        profile,
        hardware,
        train_rows,
        val_rows,
        run_path,
        seed=seed,
        max_steps=1 if smoke else -1,
        eval_steps=eval_steps,
        notify=notify,
    )
    del model, tokenizer
    gc.collect()
    torch.cuda.empty_cache()

    notify(f"Reloading selected PEFT adapter and evaluating on {len(heldout)} holdout example(s)...")
    model, tokenizer = load_model(profile, hardware, adapter=adapter)
    tuned, tuned_drafts = evaluate_model(model, tokenizer, heldout, profile, hardware)
    samples = sample_drafts(
        heldout,
        baseline_drafts,
        tuned_drafts,
        show_private=show_private,
        seed=seed,
        count=sample_count,
    )

    metrics_file = run_path / "metrics.jsonl"
    if not metrics_file.exists():
        from util.monitoring import MetricsLogger

        fallback_logger = MetricsLogger(metrics_file, stage="sft")
        for entry in history:
            if "loss" in entry:
                fallback_logger.record(
                    emit_progress=False,
                    event="train_step",
                    step=int(entry.get("step", 0)),
                    loss=float(entry["loss"]),
                )
            if "eval_loss" in entry:
                fallback_logger.record(
                    emit_progress=False,
                    event="eval",
                    step=int(entry.get("step", 0)),
                    eval_loss=float(entry["eval_loss"]),
                )
    records = read_metrics(metrics_file) or history
    loss_plot = save_figure(plot_losses(records), run_path / "loss.png")
    diagnostics_plot = save_figure(plot_sft_diagnostics(records), run_path / "training_metrics.png")
    comparison_plot = save_figure(
        plot_stage_comparison({"baseline": baseline, "sft": tuned}),
        run_path / "comparison.png",
    )

    samples_file = None
    if samples:
        samples_file = run_path / "heldout-sample-outputs.txt"
        dataset_label = (
            display_path(input_dir / "reply-conversations.jsonl")
            if input_dir is not None
            else r"workshops\email-reply\input\enron\reply-conversations.jsonl"
        )
        checkpoint_label = "one optimizer step (smoke check)" if smoke else "best validation checkpoint"
        with samples_file.open("x", encoding="utf-8") as file:
            file.write(
                format_samples(
                    samples,
                    profile,
                    hardware,
                    dataset_label=dataset_label,
                    stage_note=f"SFT checkpoint: {checkpoint_label}",
                )
            )
    result = Experiment(
        run_dir=run_path,
        baseline_run_dir=baseline_run_dir,
        metrics_file=metrics_file,
        loss_plot=loss_plot,
        diagnostics_plot=diagnostics_plot,
        comparison_plot=comparison_plot,
        samples_file=samples_file,
        baseline=baseline,
        fine_tuned=tuned,
        comparison_identity=comparison_identity,
        history=history,
        samples=samples,
        peak_allocated_mib=round(torch.cuda.max_memory_allocated() / 2**20, 1),
        peak_reserved_mib=round(torch.cuda.max_memory_reserved() / 2**20, 1),
    )
    summary = public_summary(
        result,
        profile,
        hardware,
        fit_sets,
        smoke=smoke,
        seed=seed,
        eval_steps=eval_steps,
        input_dir=input_dir,
        output_root=effective_output_root,
        split_manifest=split_manifest,
        dataset=dataset,
    )
    with (run_path / "summary.json").open("x", encoding="utf-8") as file:
        json.dump(summary, file, indent=2)
    return result


def build_parser() -> argparse.ArgumentParser:
    defaults_model = ModelProfile()
    defaults_hw = Hardware()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Prepared dataset directory containing reply-conversations.jsonl (default: input\\enron).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Ignored private output root for stage runs and split manifests (default: output).",
    )
    parser.add_argument(
        "--baseline-run",
        default=None,
        help="Optional compatible saved baseline run directory or summary.json to reuse.",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Evaluate and save only the standalone prompt-only baseline stage.",
    )
    parser.add_argument(
        "--eval-steps",
        type=int,
        default=None,
        help="Optimizer step cadence for periodic validation and checkpointing.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a bounded 1-step GPU check instead of the full dataset.",
    )
    parser.add_argument(
        "--show-private",
        action="store_true",
        help="Write sampled held-out conversations, drafts, and references into the private run folder.",
    )
    parser.add_argument(
        "--sample-count",
        type=int,
        default=None,
        help="Number of held-out comparisons to write with --show-private (default: 3).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--model-id", default=defaults_model.model_id)
    parser.add_argument(
        "--revision",
        default=defaults_model.revision,
        help="Optional base model revision (branch, tag, or commit hash).",
    )
    parser.add_argument("--target-modules", nargs="+", default=list(defaults_model.target_modules))
    parser.add_argument("--end-token", default=defaults_model.end_token)
    parser.add_argument("--max-length", type=int, default=defaults_hw.max_length)
    parser.add_argument("--completion-tokens", type=int, default=defaults_hw.completion_tokens)
    parser.add_argument("--batch-size", type=int, default=defaults_hw.batch_size)
    parser.add_argument("--accumulation", type=int, default=defaults_hw.accumulation)
    parser.add_argument(
        "--no-four-bit",
        dest="four_bit",
        action="store_false",
        help="Disable 4-bit quantization on larger GPUs.",
    )
    parser.add_argument(
        "--fp16",
        dest="bf16",
        action="store_false",
        help="Use FP16 compute instead of BF16.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.sample_count is not None and not args.show_private:
        parser.error("--sample-count requires --show-private.")
    sample_count = 3 if args.sample_count is None else args.sample_count
    if sample_count < 1:
        parser.error("--sample-count must be positive.")
    if args.eval_steps is not None and args.eval_steps < 1:
        parser.error("--eval-steps must be a positive integer.")
    if args.baseline_only and args.baseline_run is not None:
        parser.error("--baseline-only cannot be combined with --baseline-run.")
    try:
        profile = ModelProfile(
            model_id=args.model_id,
            revision=args.revision,
            target_modules=tuple(args.target_modules),
            end_token=args.end_token,
        )
        hardware = Hardware(
            max_length=args.max_length,
            completion_tokens=args.completion_tokens,
            batch_size=args.batch_size,
            accumulation=args.accumulation,
            four_bit=args.four_bit,
            bf16=args.bf16,
        )
        input_dir, dataset_path = resolve_input_dir(args.input_dir)
        output_root = prepare_output_root(args.output_dir, input_dir=input_dir)
    except ValueError as error:
        parser.error(str(error))

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    mode = "smoke (1 optimizer step)" if args.smoke else "full (pass --smoke for a fast 1-step check)"
    log(f"Mode: {mode}")
    rows, excluded, digest = load_pairs(dataset_path)
    splits = split_pairs(rows, args.seed)
    sft_out = private_output(output_root)
    split_manifest_path = sft_out / f"split-{args.seed}.json"
    split_sha256 = save_split(split_manifest_path, splits, digest, args.seed)
    dataset = {
        "source_sha256": digest,
        "accepted": len(rows),
        "splits": {name: len(split) for name, split in splits.items()},
        "holdout_fraction": round(len(splits["holdout"]) / len(rows), 4),
        "excluded": excluded,
    }
    log(
        f"Dataset: {dataset['accepted']} accepted {dataset['splits']}, "
        f"holdout_fraction={dataset['holdout_fraction']}, excluded={excluded}"
    )
    if args.baseline_only:
        runtime()
        effective_hw = (
            replace(
                hardware,
                completion_tokens=min(hardware.completion_tokens, 64),
                accumulation=1,
            )
            if args.smoke
            else hardware
        )
        model, tokenizer = load_model(profile, effective_hw)
        cases = prepare_evaluation(splits["holdout"], tokenizer, profile, effective_hw)
        heldout = [c for c in cases if c.reference is not None][:2] if args.smoke else cases
        if not heldout:
            parser.error("No holdout example available for this run.")
        comp_id = build_comparison_identity(
            dataset_sha256=digest,
            split_sha256=split_sha256,
            holdout_lines=[c.pair.line for c in heldout],
            profile=profile,
            hardware=effective_hw,
        )
        base_eval, base_drafts = evaluate_model(model, tokenizer, heldout, profile, effective_hw)
        base_dir, _ = save_baseline_run(
            output_root,
            evaluation=base_eval,
            comparison_identity=comp_id,
            profile=profile,
            hardware=effective_hw,
            heldout=heldout,
            drafts=base_drafts,
            smoke=args.smoke,
            show_private=args.show_private,
            sample_count=sample_count,
            seed=args.seed,
            input_dir=input_dir,
            dataset=dataset,
        )
        saved_base = json.loads((base_dir / "summary.json").read_text(encoding="utf-8"))
        print(json.dumps(saved_base, indent=2))
        return

    try:
        result = run(
            splits,
            profile,
            hardware,
            smoke=args.smoke,
            show_private=args.show_private,
            sample_count=sample_count,
            seed=args.seed,
            eval_steps=args.eval_steps,
            input_dir=input_dir,
            output_root=output_root,
            split_manifest=split_manifest_path,
            split_sha256=split_sha256,
            baseline_run=args.baseline_run,
            dataset=dataset,
            log=log,
        )
    except ValueError as error:
        parser.error(str(error))
    saved = json.loads((result.run_dir / "summary.json").read_text(encoding="utf-8"))
    print(json.dumps(saved, indent=2))
    if args.smoke:
        for stats in (result.baseline, result.fine_tuned):
            if not stats["valid_drafts"] or stats["generation_failures"] or not stats["reference_tokens"]:
                parser.exit(1, "The smoke run did not produce both required model outputs.\n")


if __name__ == "__main__":
    main()
