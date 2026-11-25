"""Run checkpoint-initialized QLoRA GRPO with local judging and 3-stage comparison."""

from __future__ import annotations

import argparse
import gc
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grpo.judge import (
    JudgeProfile,
    LocalJudge,
    summarize_judge_scores,
)
from grpo.trainer import (
    POLICY_ADAPTER_NAME,
    REFERENCE_ADAPTER_NAME,
    GRPOConfig,
    activate_adapter,
    fit_grpo,
    load_policy_with_sft_reference,
)
from util.data import load_frozen_split, load_pairs
from util.evaluation import (
    EvaluationCase,
    build_comparison_identity,
    evaluate_model,
    format_samples,
    load_saved_stage_summary,
    prepare_evaluation,
    sample_drafts,
    save_baseline_run,
)
from util.models import check_adapter, load_model, read_adapter_identity, runtime
from util.monitoring import plot_stage_comparison, save_figure
from util.paths import (
    REPO_ROOT,
    create_stage_run_dir,
    display_path,
    ensure_unlinked_path,
    prepare_output_root,
    resolve_input_dir,
)
from util.prompts import INSTRUCTION, Hardware, ModelProfile, format_model_ref

SMOKE_MAX_TRAIN_GROUPS = 3


@dataclass(frozen=True)
class GRPOExperiment:
    run_dir: Path
    baseline_run_dir: Path
    sft_run_dir: Path | None
    sft_adapter_dir: Path
    grpo_adapter_dir: Path
    metrics_file: Path
    diagnostics_plot: Path
    comparison_plot: Path
    samples_file: Path | None
    baseline: dict
    sft: dict
    grpo: dict
    comparison_identity: dict
    lineage: dict
    judge: dict
    history: list[dict]
    samples: list[dict]
    peak_allocated_mib: float
    peak_reserved_mib: float


def _resolve_caller_path(raw: str | Path, *, label: str) -> Path:
    text = str(raw).strip()
    if not text:
        raise ValueError(f"{label} path must be non-empty.")
    candidate = Path(text)
    target = ensure_unlinked_path(candidate if candidate.is_absolute() else (Path.cwd() / candidate))
    if not target.exists():
        raise ValueError(f"{label} does not exist: {display_path(target)}")
    return target


def resolve_sft_inputs(
    *,
    sft_run: str | Path | None,
    sft_adapter: str | Path | None,
    split_manifest: str | Path | None,
    seed: int,
) -> tuple[Path | None, Path, Path, dict | None]:
    """Resolve SFT run directory (optional), SFT adapter directory, and frozen split manifest."""
    if sft_run is None and sft_adapter is None:
        raise ValueError("Pass --sft-run <dir> or --sft-adapter <dir> to initialize GRPO from SFT.")

    sft_run_dir: Path | None = None
    sft_summary: dict | None = None
    if sft_run is not None:
        target = _resolve_caller_path(sft_run, label="SFT run")
        sft_run_dir = target if target.is_dir() else target.parent
        summary_path = target if target.is_file() else (sft_run_dir / "summary.json")
        if not summary_path.is_file():
            raise ValueError(f"SFT run summary.json not found at: {display_path(summary_path)}")
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        except ValueError as err:
            raise ValueError(f"SFT run summary.json is not valid JSON: {err}") from err
        if type(loaded) is not dict:
            raise ValueError("SFT run summary.json must contain a JSON object.")
        sft_summary = loaded

    if sft_adapter is not None:
        adapter_dir = _resolve_caller_path(sft_adapter, label="SFT adapter")
    else:
        assert sft_run_dir is not None
        adapter_dir = ensure_unlinked_path(sft_run_dir / "adapter")
    if not adapter_dir.is_dir():
        raise ValueError(f"SFT adapter directory does not exist: {display_path(adapter_dir)}")

    manifest_path: Path | None = None
    if split_manifest is not None:
        manifest_path = _resolve_caller_path(split_manifest, label="Split manifest")
    elif sft_summary is not None and isinstance(sft_summary.get("split_manifest"), str):
        recorded = Path(sft_summary["split_manifest"])
        candidates = []
        if not recorded.is_absolute():
            candidates.append(REPO_ROOT / recorded)
            if sft_run_dir is not None:
                candidates.append(sft_run_dir.parent / recorded.name)
        else:
            candidates.append(recorded)
        for cand in candidates:
            if cand.is_file():
                manifest_path = ensure_unlinked_path(cand)
                break
    elif sft_run_dir is not None:
        sibling = sft_run_dir.parent / f"split-{seed}.json"
        if sibling.is_file():
            manifest_path = ensure_unlinked_path(sibling)
    elif (adapter_dir.parent.parent / f"split-{seed}.json").is_file():
        manifest_path = ensure_unlinked_path(adapter_dir.parent.parent / f"split-{seed}.json")

    if manifest_path is None or not manifest_path.is_file():
        raise ValueError(
            "GRPO requires SFT's frozen split manifest so train/validation/holdout partitions stay identical. "
            "Pass --split-manifest <split.json> explicitly."
        )
    return sft_run_dir, adapter_dir, manifest_path, sft_summary


def _judge_holdout_drafts(
    judge: LocalJudge,
    heldout: list[EvaluationCase],
    drafts: list[str | None],
) -> dict:
    scores = []
    invalid_drafts = 0
    for case, draft in zip(heldout, drafts):
        if draft is None or not draft.strip():
            invalid_drafts += 1
            continue
        scores.append(judge.score_one(case.prompt.conversation, draft))
    summary = summarize_judge_scores(scores)
    summary["invalid_drafts"] = invalid_drafts
    return summary


def public_summary(
    result: GRPOExperiment,
    profile: ModelProfile,
    hardware: Hardware,
    config: GRPOConfig,
    *,
    smoke: bool,
    seed: int,
    input_dir: Path | None = None,
    output_root: Path | None = None,
    split_manifest: Path | None = None,
    dataset: dict | None = None,
) -> dict:
    summary: dict[str, object] = {
        "stage": "grpo",
        "smoke": smoke,
        "seed": seed,
        "instruction": INSTRUCTION,
        "note": (
            "reference_token_loss measures fit to the archived reply rather than factual correctness; "
            "judge scores are local model rubric estimates against the visible conversation, not ground-truth verification."
        ),
        "input_dir": display_path(input_dir) if input_dir is not None else None,
        "output_root": display_path(output_root) if output_root is not None else None,
        "split_manifest": display_path(split_manifest) if split_manifest is not None else None,
        "baseline_run": display_path(result.baseline_run_dir),
        "sft_run": display_path(result.sft_run_dir) if result.sft_run_dir is not None else None,
        "sft_adapter": display_path(result.sft_adapter_dir),
        "grpo_adapter": display_path(result.grpo_adapter_dir),
        "run_dir": display_path(result.run_dir),
        "metrics_file": display_path(result.metrics_file),
        "training_metrics_plot": display_path(result.diagnostics_plot),
        "comparison_plot": display_path(result.comparison_plot),
        "samples_file": display_path(result.samples_file) if result.samples_file is not None else None,
        "model": asdict(profile),
        "hardware": asdict(hardware),
        "grpo_config": asdict(config),
        "judge": result.judge,
        "lineage": result.lineage,
        "comparison_identity": result.comparison_identity,
    }
    if dataset is not None:
        summary["dataset"] = dataset
    summary.update({
        "baseline": result.baseline,
        "sft": result.sft,
        "grpo": result.grpo,
        "history": result.history,
        "peak_allocated_mib": result.peak_allocated_mib,
        "peak_reserved_mib": result.peak_reserved_mib,
    })
    return summary


def run(
    splits: dict,
    profile: ModelProfile,
    hardware: Hardware,
    judge_profile: JudgeProfile,
    config: GRPOConfig,
    *,
    sft_adapter: Path,
    dataset_sha256: str,
    split_sha256: str,
    sft_run: str | Path | None = None,
    baseline_run: str | Path | None = None,
    smoke: bool = False,
    show_private: bool = False,
    sample_count: int = 3,
    seed: int = 42,
    input_dir: Path | None = None,
    output_root: Path | None = None,
    split_manifest: Path | None = None,
    dataset: dict | None = None,
    judge_instance: LocalJudge | None = None,
    log: Callable[[str], None] | None = None,
) -> GRPOExperiment:
    if sample_count < 1:
        raise ValueError("Sample count must be positive.")
    notify = log or (lambda _: None)
    sft_dir = ensure_unlinked_path(sft_adapter)
    check_adapter(sft_dir, profile)

    resolved_root = prepare_output_root(output_root, input_dir=input_dir)
    torch_mod, _ = runtime()
    if smoke:
        hardware = replace(
            hardware,
            completion_tokens=min(hardware.completion_tokens, 64),
            accumulation=1,
        )
        if config.max_steps == -1:
            config = replace(config, max_steps=SMOKE_MAX_TRAIN_GROUPS)
    if torch_mod.cuda.is_available():
        torch_mod.cuda.reset_peak_memory_stats()

    cap = {"train": max(4, config.max_steps), "validation": 2, "holdout": 2}

    def select(tokenizer, name: str) -> list[EvaluationCase]:
        cases = prepare_evaluation(splits[name], tokenizer, profile, hardware)
        if not smoke:
            return cases
        return [case for case in cases if case.reference is not None][: cap[name]]

    judge = judge_instance
    if judge is None:
        notify(
            f"Loading frozen local judge {format_model_ref(judge_profile.model_id, judge_profile.revision)} "
            f"on {judge_profile.device}..."
        )
        judge = LocalJudge(judge_profile)

    # Load 4-bit base model first to evaluate/verify baseline before attaching SFT adapters,
    # unless a saved baseline run already provides compatible metrics and judge scores.
    notify(f"Loading base model {format_model_ref(profile.model_id, profile.revision)}...")
    base_model, base_tokenizer = load_model(profile, hardware)
    heldout = select(base_tokenizer, "holdout")
    if not heldout:
        raise ValueError("No holdout example available for GRPO comparison.")

    comparison_identity = build_comparison_identity(
        dataset_sha256=dataset_sha256,
        split_sha256=split_sha256,
        holdout_lines=[case.pair.line for case in heldout],
        profile=profile,
        hardware=hardware,
    )

    sft_run_dir: Path | None = None
    saved_sft_eval: dict | None = None
    if sft_run is not None:
        notify(f"Validating saved SFT run provenance from {sft_run}...")
        sft_run_dir, saved_sft_summary = load_saved_stage_summary(
            sft_run,
            comparison_identity,
            label="sft",
            expected_stage="sft",
        )
        raw_sft = saved_sft_summary.get("fine_tuned") or saved_sft_summary.get("sft")
        if type(raw_sft) is dict:
            saved_sft_eval = dict(raw_sft)

    if baseline_run is not None:
        notify(f"Validating saved baseline provenance from {baseline_run}...")
        baseline_run_dir, saved_base = load_saved_stage_summary(
            baseline_run,
            comparison_identity,
            label="baseline",
            expected_stage="baseline",
        )
        raw_base = saved_base.get("evaluation") or saved_base.get("baseline")
        if type(raw_base) is not dict:
            raise ValueError("Saved baseline summary is missing evaluation metrics.")
        baseline_eval = dict(raw_base)
        notify(f"Generating baseline holdout drafts across {len(heldout)} example(s) for rubric comparison...")
        _, baseline_drafts = evaluate_model(base_model, base_tokenizer, heldout, profile, hardware)
    else:
        notify(f"Evaluating unadapted base model on {len(heldout)} holdout example(s)...")
        baseline_eval, baseline_drafts = evaluate_model(
            base_model, base_tokenizer, heldout, profile, hardware
        )
        baseline_run_dir, _ = save_baseline_run(
            resolved_root,
            evaluation=baseline_eval,
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

    del base_model, base_tokenizer
    gc.collect()
    if torch_mod.cuda.is_available():
        torch_mod.cuda.empty_cache()

    notify(f"Scoring {len(baseline_drafts)} baseline holdout draft(s) with local judge...")
    baseline_eval = {
        **baseline_eval,
        "judge": _judge_holdout_drafts(judge, heldout, baseline_drafts),
    }
    if torch_mod.cuda.is_available():
        torch_mod.cuda.empty_cache()

    notify(f"Loading trainable SFT policy + frozen '{REFERENCE_ADAPTER_NAME}' reference from {display_path(sft_dir)}...")
    policy_model, tokenizer = load_policy_with_sft_reference(profile, hardware, sft_dir)
    fit_sets = {name: select(tokenizer, name) for name in ("train", "validation")}
    train_prompts = [case.prompt for case in fit_sets["train"]]
    val_prompts = [case.prompt for case in fit_sets["validation"]]

    # Evaluate frozen SFT reference on holdout (exact SFT checkpoint behavior + judge rubric).
    notify(f"Evaluating frozen SFT reference across {len(heldout)} holdout example(s)...")
    activate_adapter(policy_model, REFERENCE_ADAPTER_NAME, training=False)
    fresh_sft_eval, sft_drafts = evaluate_model(policy_model, tokenizer, heldout, profile, hardware)
    notify(f"Scoring {len(sft_drafts)} SFT holdout draft(s) with local judge...")
    sft_eval = dict(saved_sft_eval) if saved_sft_eval is not None else dict(fresh_sft_eval)
    sft_eval["judge"] = _judge_holdout_drafts(judge, heldout, sft_drafts)
    if torch_mod.cuda.is_available():
        torch_mod.cuda.empty_cache()

    run_dir = create_stage_run_dir(resolved_root, "grpo", smoke=smoke)
    notify(
        f"Training QLoRA GRPO ({len(train_prompts)} train prompt(s), {len(val_prompts)} validation prompt(s), "
        f"group_size={config.group_size}, beta={config.beta})..."
    )
    activate_adapter(policy_model, POLICY_ADAPTER_NAME, training=True)
    fit_result = fit_grpo(
        policy_model,
        tokenizer,
        judge,
        profile,
        hardware,
        config,
        train_prompts,
        val_prompts,
        run_dir,
        sft_adapter=sft_dir,
        sft_run_dir=sft_run_dir,
        dataset_sha256=dataset_sha256,
        split_sha256=split_sha256,
        seed=seed,
        smoke=smoke,
        require_update=True,
        stop_after_first_update=smoke,
        notify=notify,
    )

    del policy_model, tokenizer
    gc.collect()
    if torch_mod.cuda.is_available():
        torch_mod.cuda.empty_cache()

    notify("Reloading saved GRPO PEFT adapter for held-out evaluation...")
    grpo_model, grpo_tokenizer = load_model(profile, hardware, adapter=fit_result.adapter_dir)
    grpo_eval, grpo_drafts = evaluate_model(grpo_model, grpo_tokenizer, heldout, profile, hardware)

    peak_alloc = (
        round(torch_mod.cuda.max_memory_allocated() / (1024**2), 1)
        if torch_mod.cuda.is_available()
        else 0.0
    )
    peak_res = (
        round(torch_mod.cuda.max_memory_reserved() / (1024**2), 1)
        if torch_mod.cuda.is_available()
        else 0.0
    )
    del grpo_model, grpo_tokenizer
    gc.collect()
    if torch_mod.cuda.is_available():
        torch_mod.cuda.empty_cache()

    notify(f"Scoring {len(grpo_drafts)} GRPO holdout draft(s) with local judge...")
    grpo_eval["judge"] = _judge_holdout_drafts(judge, heldout, grpo_drafts)

    comparison_plot = run_dir / "comparison.png"
    save_figure(
        plot_stage_comparison({"baseline": baseline_eval, "sft": sft_eval, "grpo": grpo_eval}),
        comparison_plot,
    )

    samples = sample_drafts(
        heldout,
        baseline_drafts,
        sft_drafts,
        grpo=grpo_drafts,
        show_private=show_private,
        seed=seed,
        count=sample_count,
    )
    samples_file: Path | None = None
    if samples:
        samples_file = run_dir / "heldout-sample-outputs.txt"
        dataset_label = (
            display_path(input_dir / "reply-conversations.jsonl")
            if input_dir is not None
            else r"workshops\email-reply\input\enron\reply-conversations.jsonl"
        )
        with samples_file.open("x", encoding="utf-8") as handle:
            handle.write(
                format_samples(
                    samples,
                    profile,
                    hardware,
                    dataset_label=dataset_label,
                    stage_note="Comparison: unadapted base vs. QLoRA SFT vs. QLoRA GRPO",
                )
            )

    result = GRPOExperiment(
        run_dir=run_dir,
        baseline_run_dir=baseline_run_dir,
        sft_run_dir=sft_run_dir,
        sft_adapter_dir=sft_dir,
        grpo_adapter_dir=fit_result.adapter_dir,
        metrics_file=fit_result.metrics_file,
        diagnostics_plot=fit_result.diagnostics_plot,
        comparison_plot=comparison_plot,
        samples_file=samples_file,
        baseline=baseline_eval,
        sft=sft_eval,
        grpo=grpo_eval,
        comparison_identity=comparison_identity,
        lineage=fit_result.lineage,
        judge=judge.provenance(),
        history=fit_result.history,
        samples=samples,
        peak_allocated_mib=peak_alloc,
        peak_reserved_mib=peak_res,
    )

    summary = public_summary(
        result,
        profile,
        hardware,
        config,
        smoke=smoke,
        seed=seed,
        input_dir=input_dir,
        output_root=resolved_root,
        split_manifest=split_manifest,
        dataset=dataset,
    )
    with (run_dir / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return result


def build_parser() -> argparse.ArgumentParser:
    defaults_model = ModelProfile()
    defaults_hw = Hardware()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        default=None,
        help="Input dataset folder containing reply-conversations.jsonl (defaults to input\\enron).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output root folder for baseline\\, sft\\, and grpo\\ stage runs (defaults to output).",
    )
    parser.add_argument(
        "--sft-run",
        default=None,
        help="Existing SFT run directory or summary.json (validates provenance and locates adapter).",
    )
    parser.add_argument(
        "--sft-adapter",
        default=None,
        help="Existing portable SFT PEFT adapter directory to initialize GRPO from.",
    )
    parser.add_argument(
        "--split-manifest",
        default=None,
        help="Frozen split-<seed>.json manifest produced by SFT for identical partitions.",
    )
    parser.add_argument(
        "--baseline-run",
        default=None,
        help="Existing baseline run directory or summary.json to validate and reuse.",
    )
    parser.add_argument(
        "--model-id",
        "--base-model",
        dest="model_id",
        default=defaults_model.model_id,
        help="Base Hugging Face model ID.",
    )
    parser.add_argument(
        "--revision",
        "--base-revision",
        dest="revision",
        default=defaults_model.revision,
        help="Optional base model revision (branch, tag, or commit hash).",
    )
    parser.add_argument("--end-token", default=defaults_model.end_token, help="Chat end-of-turn token.")
    parser.add_argument(
        "--target-modules",
        nargs="+",
        default=None,
        help="LoRA target module names (space- or comma-separated).",
    )
    parser.add_argument(
        "--judge-model-id",
        default=JudgeProfile().model_id,
        help=(
            f"Local or cached Hugging Face causal LM ID for the frozen rubric judge "
            f"(default: {JudgeProfile().model_id}; no hosted API)."
        ),
    )
    parser.add_argument(
        "--judge-revision",
        default=None,
        help="Optional revision (branch, tag, or commit hash) for the frozen local judge model.",
    )
    parser.add_argument(
        "--judge-device",
        default="cpu",
        help="Local device for judge inference (default: cpu; pass cuda when VRAM allows).",
    )
    parser.add_argument(
        "--judge-max-input-tokens",
        type=int,
        default=3072,
        help="Maximum input token budget for judge prompts.",
    )
    parser.add_argument(
        "--judge-max-new-tokens",
        type=int,
        default=160,
        help="Maximum generated tokens for structured judge JSON responses.",
    )
    parser.add_argument(
        "--judge-four-bit",
        action="store_true",
        help="Load the local judge in 4-bit NF4 when running on CUDA.",
    )
    parser.add_argument("--group-size", type=int, default=4, help="Sampled completions per prompt (>= 2).")
    parser.add_argument("--temperature", type=float, default=0.8, help="Rollout sampling temperature (> 0).")
    parser.add_argument("--top-p", type=float, default=0.95, help="Rollout nucleus sampling top-p.")
    parser.add_argument(
        "--beta",
        type=float,
        default=0.04,
        help="Positive KL regularization coefficient toward the frozen SFT reference.",
    )
    parser.add_argument("--learning-rate", type=float, default=2e-5, help="AdamW learning rate.")
    parser.add_argument("--max-steps", type=int, default=-1, help="Optional optimizer step cap (-1 for full pass).")
    parser.add_argument(
        "--eval-steps",
        type=int,
        default=None,
        help="Run periodic validation and checkpoint selection every N steps.",
    )
    parser.add_argument(
        "--eval-max-cases",
        type=int,
        default=None,
        help="Optional cap on validation prompts per intermediate GRPO check (full holdout stays unchanged).",
    )
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
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--sample-count",
        "--samples",
        dest="sample_count",
        type=int,
        default=None,
        help="Number of held-out comparisons to write with --show-private (default: 3).",
    )
    parser.add_argument("--smoke", action="store_true", help="Run a bounded GPU smoke check.")
    parser.add_argument(
        "--show-private",
        action="store_true",
        help="Write local held-out conversations, drafts, and archived replies into the run folder.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_length <= args.completion_tokens:
        parser.error("--max-length must be greater than --completion-tokens.")
    if args.sample_count is not None and not args.show_private:
        parser.error("--sample-count requires --show-private.")
    sample_count = 3 if args.sample_count is None else args.sample_count
    if sample_count < 1:
        parser.error("--sample-count must be positive.")

    if args.target_modules is not None:
        parsed_targets = tuple(
            part.strip()
            for token in args.target_modules
            for part in token.split(",")
            if part.strip()
        )
    else:
        parsed_targets = ModelProfile().target_modules

    try:
        profile = ModelProfile(
            model_id=args.model_id,
            revision=args.revision,
            end_token=args.end_token,
            target_modules=parsed_targets,
        )
        hardware = Hardware(
            max_length=args.max_length,
            completion_tokens=args.completion_tokens,
            batch_size=args.batch_size,
            accumulation=args.accumulation,
            four_bit=args.four_bit,
            bf16=args.bf16,
        )
        judge_profile = JudgeProfile(
            model_id=args.judge_model_id,
            revision=args.judge_revision,
            device=args.judge_device,
            max_input_tokens=args.judge_max_input_tokens,
            max_new_tokens=args.judge_max_new_tokens,
            four_bit=args.judge_four_bit,
        )
        config = GRPOConfig(
            group_size=args.group_size,
            temperature=args.temperature,
            top_p=args.top_p,
            beta=args.beta,
            learning_rate=args.learning_rate,
            max_steps=args.max_steps,
            eval_steps=args.eval_steps,
            eval_max_cases=args.eval_max_cases,
        )
        input_dir, dataset_path = resolve_input_dir(args.input_dir)
        output_root = prepare_output_root(args.output_dir, input_dir=input_dir)
        sft_run_dir, sft_adapter_dir, manifest_path, _ = resolve_sft_inputs(
            sft_run=args.sft_run,
            sft_adapter=args.sft_adapter,
            split_manifest=args.split_manifest,
            seed=args.seed,
        )
        if args.revision is None:
            saved_meta = read_adapter_identity(sft_adapter_dir)
            if (
                saved_meta.get("base_model") == profile.model_id
                and saved_meta.get("revision") is not None
            ):
                profile = replace(profile, revision=saved_meta["revision"])
        rows, excluded, digest = load_pairs(dataset_path)
        splits, _manifest, split_sha256 = load_frozen_split(manifest_path, rows, digest)
        data_report = {
            "source_sha256": digest,
            "accepted": len(rows),
            "splits": {name: len(split) for name, split in splits.items()},
            "holdout_fraction": round(len(splits["holdout"]) / len(rows), 4),
            "excluded": excluded,
        }
        check_adapter(sft_adapter_dir, profile)
        result = run(
            splits,
            profile,
            hardware,
            judge_profile,
            config,
            sft_adapter=sft_adapter_dir,
            dataset_sha256=digest,
            split_sha256=split_sha256,
            sft_run=sft_run_dir if args.sft_run is not None else None,
            baseline_run=args.baseline_run,
            smoke=args.smoke,
            show_private=args.show_private,
            sample_count=sample_count,
            seed=args.seed,
            input_dir=input_dir,
            output_root=output_root,
            split_manifest=manifest_path,
            dataset=data_report,
            log=lambda msg: print(msg, file=sys.stderr, flush=True),
        )
    except (ValueError, RuntimeError) as err:
        raise SystemExit(str(err)) from err

    print(
        json.dumps(
            public_summary(
                result,
                profile,
                hardware,
                config,
                smoke=args.smoke,
                seed=args.seed,
                input_dir=input_dir,
                output_root=output_root,
                split_manifest=manifest_path,
                dataset=data_report,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
