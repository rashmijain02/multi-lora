"""Checkpoint-initialized QLoRA GRPO trainer with frozen SFT reference KL and telemetry."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from grpo.judge import JudgeScore, LocalJudge, summarize_judge_scores
from util.models import adapter_fingerprint, adapter_identity, check_adapter, load_model, runtime
from util.monitoring import (
    MetricsLogger,
    plot_grpo_diagnostics,
    resolve_eval_steps,
    save_figure,
)
from util.paths import display_path, ensure_unlinked_path, restrict_directory
from util.prompts import Hardware, ModelProfile, Prompt, end_id

POLICY_ADAPTER_NAME = "default"
REFERENCE_ADAPTER_NAME = "sft_ref"
ADVANTAGE_EPS = 1e-8


@dataclass(frozen=True)
class GRPOConfig:
    group_size: int = 4
    temperature: float = 0.8
    top_p: float = 0.95
    beta: float = 0.04
    learning_rate: float = 2e-5
    max_grad_norm: float = 1.0
    max_steps: int = -1
    eval_steps: int | None = None
    eval_max_cases: int | None = None

    def __post_init__(self) -> None:
        if type(self.group_size) is not int or self.group_size < 2:
            raise ValueError("GRPO group_size must be an integer >= 2.")
        if not math.isfinite(self.temperature) or self.temperature <= 0.0:
            raise ValueError("GRPO temperature must be a finite positive float.")
        if not math.isfinite(self.top_p) or not (0.0 < self.top_p <= 1.0):
            raise ValueError("GRPO top_p must be in (0.0, 1.0].")
        if not math.isfinite(self.beta) or self.beta <= 0.0:
            raise ValueError(
                "GRPO beta must be a finite positive float to regularize against the frozen SFT reference."
            )
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("GRPO learning_rate must be a finite positive float.")
        if not math.isfinite(self.max_grad_norm) or self.max_grad_norm <= 0.0:
            raise ValueError("GRPO max_grad_norm must be a finite positive float.")
        if type(self.max_steps) is not int or self.max_steps == 0 or self.max_steps < -1:
            raise ValueError("GRPO max_steps must be -1 or a positive integer.")
        if self.eval_steps is not None and (type(self.eval_steps) is not int or self.eval_steps < 1):
            raise ValueError("GRPO eval_steps must be None or a positive integer.")
        if self.eval_max_cases is not None and (
            type(self.eval_max_cases) is not int or self.eval_max_cases < 1
        ):
            raise ValueError("GRPO eval_max_cases must be None or a positive integer.")


@dataclass(frozen=True)
class GRPOFitResult:
    adapter_dir: Path
    lineage_file: Path
    metrics_file: Path
    diagnostics_plot: Path
    history: list[dict]
    lineage: dict


def compute_group_advantages(rewards: list[float]) -> tuple[list[float], float, bool]:
    """Compute group-relative normalized advantages without fabricating variance on ties.

    Returns ``(advantages, reward_std, is_tied)``.
    """
    if len(rewards) < 2:
        return [0.0 for _ in rewards], 0.0, True
    for value in rewards:
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ValueError(f"Non-finite or invalid scalar reward in group: {value!r}")
    mean_r = sum(rewards) / len(rewards)
    variance = sum((value - mean_r) ** 2 for value in rewards) / len(rewards)
    std_r = math.sqrt(max(0.0, variance))
    if std_r <= ADVANTAGE_EPS:
        return [0.0 for _ in rewards], 0.0, True
    return [(value - mean_r) / std_r for value in rewards], std_r, False


def _adapter_parameters(model: object, adapter_name: str) -> dict[str, object]:
    named_params = getattr(model, "named_parameters", None)
    if not callable(named_params):
        return {}
    needle = f".{adapter_name}."
    matched = {name: param for name, param in named_params() if needle in name or name.endswith(f".{adapter_name}")}
    if matched:
        return matched
    if adapter_name == POLICY_ADAPTER_NAME:
        return {
            name: param
            for name, param in named_params()
            if REFERENCE_ADAPTER_NAME not in name and ("lora_" in name or getattr(param, "requires_grad", False))
        }
    return {}


def _snapshot_tensors(params: dict[str, object]) -> dict[str, object]:
    return {name: param.detach().cpu().clone() for name, param in params.items()}


def _restore_tensors(params: dict[str, object], snapshot: dict[str, object]) -> None:
    import torch

    with torch.no_grad():
        for name, param in params.items():
            if name in snapshot:
                param.copy_(snapshot[name].to(device=param.device, dtype=param.dtype))


def _max_tensor_delta(params: dict[str, object], snapshot: dict[str, object]) -> float:
    max_delta = 0.0
    for name, param in params.items():
        if name not in snapshot:
            continue
        ref = snapshot[name].to(device=param.device, dtype=param.dtype)
        delta = float((param.detach() - ref).abs().max().item())
        max_delta = max(max_delta, delta)
    return max_delta


def activate_adapter(model: object, adapter_name: str, *, training: bool) -> None:
    """Switch active named PEFT adapter without ever calling ``disable_adapter()``."""
    setter = getattr(model, "set_adapter", None)
    if not callable(setter):
        raise TypeError(
            "GRPO model must expose set_adapter(name) to route between trainable policy and frozen SFT reference."
        )
    setter(adapter_name)
    for param in _adapter_parameters(model, REFERENCE_ADAPTER_NAME).values():
        param.requires_grad_(False)
    policy_params = _adapter_parameters(model, POLICY_ADAPTER_NAME)
    if adapter_name == POLICY_ADAPTER_NAME and training:
        for param in policy_params.values():
            param.requires_grad_(True)
        model.train()
    else:
        for param in policy_params.values():
            param.requires_grad_(False)
        model.eval()


def load_policy_with_sft_reference(
    profile: ModelProfile,
    hardware: Hardware,
    sft_adapter: Path,
):
    """Load 4-bit base model with trainable SFT adapter + frozen ``sft_ref`` adapter."""
    sft_dir = ensure_unlinked_path(sft_adapter)
    check_adapter(sft_dir, profile)
    model, tokenizer = load_model(
        profile,
        hardware,
        adapter=sft_dir,
        is_trainable=True,
        adapter_name=POLICY_ADAPTER_NAME,
    )
    loader = getattr(model, "load_adapter", None)
    if not callable(loader):
        raise TypeError("Loaded PEFT model does not support load_adapter for frozen SFT reference.")
    loader(str(sft_dir), adapter_name=REFERENCE_ADAPTER_NAME, is_trainable=False)
    enable_grads = getattr(model, "enable_input_require_grads", None)
    if callable(enable_grads):
        enable_grads()
    enable_ckpt = getattr(model, "gradient_checkpointing_enable", None)
    if callable(enable_ckpt):
        enable_ckpt(gradient_checkpointing_kwargs={"use_reentrant": False})
    activate_adapter(model, POLICY_ADAPTER_NAME, training=True)

    policy_params = _adapter_parameters(model, POLICY_ADAPTER_NAME)
    ref_params = _adapter_parameters(model, REFERENCE_ADAPTER_NAME)
    if not policy_params:
        raise ValueError("Trainable GRPO policy adapter exposed no trainable LoRA parameters.")
    if not ref_params:
        raise ValueError("Frozen SFT reference adapter exposed no reference LoRA parameters.")
    if any(param.requires_grad for param in ref_params.values()):
        raise ValueError("Frozen SFT reference adapter parameters must not require gradients.")
    return model, tokenizer


def _completion_token_logprobs(
    model: object, prompt_ids: list[int] | tuple[int, ...], completion_ids: list[int]
):
    """Compute per-token log-probabilities over completion tokens only."""
    import torch
    import torch.nn.functional as F

    if not completion_ids:
        raise ValueError("Completion token sequence must be non-empty.")
    full_ids = list(prompt_ids) + list(completion_ids)
    device = getattr(model, "device", "cpu")
    inputs = torch.tensor([full_ids], dtype=torch.long, device=device)
    attention_mask = torch.ones_like(inputs)
    outputs = model(input_ids=inputs, attention_mask=attention_mask, use_cache=False)
    logits = outputs.logits
    start = len(prompt_ids) - 1
    end = len(full_ids) - 1
    step_logits = logits[0, start:end, :].float()
    targets = torch.tensor(completion_ids, dtype=torch.long, device=step_logits.device)
    log_probs = F.log_softmax(step_logits, dim=-1)
    return log_probs.gather(dim=-1, index=targets.unsqueeze(-1)).squeeze(-1)


def _trim_at_stop(token_ids: list[int], stop_id: int) -> list[int]:
    if stop_id in token_ids:
        cut = token_ids.index(stop_id)
        return token_ids[: cut + 1]
    return token_ids


def _evaluate_validation_prompts(
    model: object,
    tokenizer: object,
    prompts: list[Prompt],
    judge: LocalJudge,
    profile: ModelProfile,
    hardware: Hardware,
) -> dict[str, float | int]:
    import torch

    activate_adapter(model, POLICY_ADAPTER_NAME, training=False)
    stop = end_id(tokenizer, profile)
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else stop
    device = getattr(model, "device", "cpu")

    valid_scores: list[JudgeScore] = []
    selection_rewards: list[float] = []
    invalid_count = 0

    for prompt in prompts:
        inputs = torch.tensor([prompt.ids], dtype=torch.long, device=device)
        try:
            with torch.no_grad():
                generated = model.generate(
                    input_ids=inputs,
                    attention_mask=torch.ones_like(inputs),
                    max_new_tokens=hardware.completion_tokens,
                    do_sample=False,
                    eos_token_id=stop,
                    pad_token_id=pad,
                )
            comp_ids = generated[0, len(prompt.ids) :].tolist()
            draft = tokenizer.decode(comp_ids, skip_special_tokens=True).strip()
        except RuntimeError as err:
            if "out of memory" in str(err).lower():
                raise
            draft = ""
        if not draft:
            invalid_count += 1
            selection_rewards.append(0.0)
            continue
        score = judge.score_one(prompt.conversation, draft)
        valid_scores.append(score)
        selection_rewards.append(score.reward)

    summary = summarize_judge_scores(valid_scores)
    selection_mean = sum(selection_rewards) / len(selection_rewards) if selection_rewards else 0.0
    return {
        "val_selection_reward": selection_mean,
        "val_reward_mean": summary["reward_mean"] if summary["reward_mean"] is not None else 0.0,
        "val_relevance_mean": summary["relevance_mean"] if summary["relevance_mean"] is not None else 0.0,
        "val_grounding_mean": summary["grounding_mean"] if summary["grounding_mean"] is not None else 0.0,
        "val_uncertainty_mean": summary["uncertainty_mean"] if summary["uncertainty_mean"] is not None else 0.0,
        "val_scored_count": int(summary["scored_count"]),
        "val_invalid_completions": invalid_count,
    }


def _save_policy_adapter(model: object, adapter_dir: Path, profile: ModelProfile, lineage: dict) -> None:
    ensure_unlinked_path(adapter_dir)
    save_pretrained = getattr(model, "save_pretrained", None)
    if not callable(save_pretrained):
        raise TypeError("Model does not expose save_pretrained for portable PEFT export.")
    try:
        save_pretrained(adapter_dir, selected_adapters=[POLICY_ADAPTER_NAME])
    except TypeError:
        activate_adapter(model, POLICY_ADAPTER_NAME, training=False)
        save_pretrained(adapter_dir)
    nested = adapter_dir / POLICY_ADAPTER_NAME
    if nested.is_dir() and not (adapter_dir / "adapter_config.json").exists():
        for child in nested.iterdir():
            child.replace(adapter_dir / child.name)
        nested.rmdir()
    restrict_directory(adapter_dir)
    (adapter_dir / "experiment-base.json").write_text(
        json.dumps(adapter_identity(profile), indent=2),
        encoding="utf-8",
    )
    (adapter_dir / "grpo-lineage.json").write_text(
        json.dumps(lineage, indent=2),
        encoding="utf-8",
    )
    check_adapter(adapter_dir, profile)


def fit_grpo(
    model: object,
    tokenizer: object,
    judge: LocalJudge,
    profile: ModelProfile,
    hardware: Hardware,
    config: GRPOConfig,
    train_prompts: list[Prompt],
    validation_prompts: list[Prompt],
    output: Path,
    *,
    sft_adapter: Path,
    sft_run_dir: Path | None = None,
    dataset_sha256: str,
    split_sha256: str,
    seed: int = 42,
    smoke: bool = False,
    require_update: bool = True,
    stop_after_first_update: bool = False,
    notify: Callable[[str], None] | None = None,
) -> GRPOFitResult:
    """Optimize trainable SFT policy with grouped rollouts, local judge rewards, and frozen SFT KL."""
    if not train_prompts or not validation_prompts:
        raise ValueError("GRPO training and validation must each contain at least one prompt.")
    torch_mod, _ = runtime()
    torch_mod.manual_seed(seed)
    if torch_mod.cuda.is_available():
        torch_mod.cuda.manual_seed_all(seed)

    sft_dir = ensure_unlinked_path(sft_adapter)
    check_adapter(sft_dir, profile)
    source_sft_fp = adapter_fingerprint(sft_dir)

    ensure_unlinked_path(output)
    if not output.exists():
        output.mkdir(mode=0o700, exist_ok=False)
        restrict_directory(output)
    elif not output.is_dir():
        raise ValueError(f"GRPO output destination is not a directory: {output.name}")

    activate_adapter(model, POLICY_ADAPTER_NAME, training=True)
    policy_params = _adapter_parameters(model, POLICY_ADAPTER_NAME)
    ref_params = _adapter_parameters(model, REFERENCE_ADAPTER_NAME)
    if not policy_params:
        raise ValueError("GRPO model has no trainable policy adapter parameters.")
    if not ref_params:
        raise ValueError("GRPO model is missing frozen SFT reference ('sft_ref') parameters.")

    initial_policy_snapshot = _snapshot_tensors(policy_params)
    initial_ref_snapshot = _snapshot_tensors(ref_params)

    optimizer = torch_mod.optim.AdamW(
        list(policy_params.values()),
        lr=config.learning_rate,
    )

    planned_steps = config.max_steps if config.max_steps > 0 else len(train_prompts)
    effective_eval_steps = resolve_eval_steps(
        config.eval_steps,
        total_steps=planned_steps,
        smoke=smoke,
    )
    active_val_prompts = (
        validation_prompts[: config.eval_max_cases]
        if config.eval_max_cases is not None
        else validation_prompts
    )

    metrics_path = output / "metrics.jsonl"
    diagnostics_path = output / "training_metrics.png"
    logger = MetricsLogger(metrics_path, stage="grpo", notify=notify)

    stop = end_id(tokenizer, profile)
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else stop
    device = getattr(model, "device", "cpu")

    optimizer_updates = 0
    total_tied_groups = 0
    total_invalid_completions = 0
    best_val_reward: float | None = None
    best_step: int | None = None
    best_policy_snapshot: dict[str, object] | None = None
    completed_steps = 0

    try:
        for step in range(1, planned_steps + 1):
            step_t0 = time.perf_counter()
            prompt = train_prompts[(step - 1) % len(train_prompts)]

            # 1. Sample grouped completions from current trainable policy.
            activate_adapter(model, POLICY_ADAPTER_NAME, training=False)
            rollout_t0 = time.perf_counter()
            valid_completions: list[tuple[list[int], str]] = []
            step_invalid = 0
            inputs = torch_mod.tensor([prompt.ids], dtype=torch_mod.long, device=device)
            mask = torch_mod.ones_like(inputs)

            for _ in range(config.group_size):
                try:
                    with torch_mod.no_grad():
                        seq = model.generate(
                            input_ids=inputs,
                            attention_mask=mask,
                            max_new_tokens=hardware.completion_tokens,
                            do_sample=True,
                            temperature=config.temperature,
                            top_p=config.top_p,
                            eos_token_id=stop,
                            pad_token_id=pad,
                        )
                    raw_comp = seq[0, len(prompt.ids) :].tolist()
                    comp_ids = _trim_at_stop(raw_comp, stop)
                    text = tokenizer.decode(comp_ids, skip_special_tokens=True).strip()
                except RuntimeError as err:
                    if "out of memory" in str(err).lower():
                        raise
                    comp_ids = []
                    text = ""
                if not comp_ids or not text:
                    step_invalid += 1
                    total_invalid_completions += 1
                else:
                    valid_completions.append((comp_ids, text))
            rollout_seconds = time.perf_counter() - rollout_t0

            # 2. Score valid completions with frozen local judge.
            judge_t0 = time.perf_counter()
            scores: list[JudgeScore] = [
                judge.score_one(prompt.conversation, draft_text)
                for _, draft_text in valid_completions
            ]
            judge_seconds = time.perf_counter() - judge_t0

            rewards = [item.reward for item in scores]
            advantages, reward_std, is_tied = compute_group_advantages(rewards)
            if is_tied:
                total_tied_groups += 1

            # 3. Compute frozen SFT reference logprobs ("sft_ref", NEVER disable_adapter()).
            ref_logps_list: list[object] = []
            if valid_completions:
                activate_adapter(model, REFERENCE_ADAPTER_NAME, training=False)
                with torch_mod.no_grad():
                    for comp_ids, _ in valid_completions:
                        ref_logps_list.append(
                            _completion_token_logprobs(model, prompt.ids, comp_ids).detach()
                        )

            # 4. Compute GRPO loss & update policy only when group has distinguishable rewards.
            step_kl_values: list[float] = []
            step_loss_value = 0.0
            grad_norm_value = 0.0
            step_updated = False

            if len(valid_completions) >= 2 and not is_tied:
                activate_adapter(model, POLICY_ADAPTER_NAME, training=True)
                optimizer.zero_grad()
                denom = float(len(valid_completions))
                for (comp_ids, _), adv, ref_logps in zip(valid_completions, advantages, ref_logps_list):
                    pol_logps = _completion_token_logprobs(model, prompt.ids, comp_ids)
                    per_token_kl = (
                        torch_mod.exp(ref_logps - pol_logps) - (ref_logps - pol_logps) - 1.0
                    )
                    ratio = torch_mod.exp(pol_logps - pol_logps.detach())
                    cand_loss = (-(ratio * adv - config.beta * per_token_kl)).mean() / denom
                    if not torch_mod.isfinite(cand_loss):
                        raise ValueError("Non-finite GRPO candidate loss encountered.")
                    cand_loss.backward()
                    step_loss_value += float(cand_loss.detach().item())
                    step_kl_values.append(float(per_token_kl.detach().mean().item()))

                pre_step_snapshot = _snapshot_tensors(policy_params)
                total_norm = torch_mod.nn.utils.clip_grad_norm_(
                    list(policy_params.values()),
                    config.max_grad_norm,
                )
                grad_norm_value = float(
                    total_norm.item() if hasattr(total_norm, "item") else total_norm
                )
                optimizer.step()
                optimizer.zero_grad()
                if _max_tensor_delta(policy_params, pre_step_snapshot) > 0.0:
                    optimizer_updates += 1
                    step_updated = True
            elif valid_completions:
                activate_adapter(model, POLICY_ADAPTER_NAME, training=False)
                with torch_mod.no_grad():
                    for (comp_ids, _), ref_logps in zip(valid_completions, ref_logps_list):
                        pol_logps = _completion_token_logprobs(model, prompt.ids, comp_ids)
                        per_token_kl = (
                            torch_mod.exp(ref_logps - pol_logps) - (ref_logps - pol_logps) - 1.0
                        )
                        step_kl_values.append(float(per_token_kl.mean().item()))
                step_loss_value = config.beta * (
                    sum(step_kl_values) / len(step_kl_values) if step_kl_values else 0.0
                )

            # Verify frozen SFT reference weights never changed during step.
            if _max_tensor_delta(ref_params, initial_ref_snapshot) > 0.0:
                raise RuntimeError("Frozen SFT reference adapter ('sft_ref') weights mutated during GRPO.")

            score_summary = summarize_judge_scores(scores)
            word_counts = [len(text.split()) for _, text in valid_completions]
            cuda_alloc = None
            cuda_res = None
            if torch_mod.cuda.is_available():
                cuda_alloc = round(torch_mod.cuda.memory_allocated() / (1024**2), 1)
                cuda_res = round(torch_mod.cuda.memory_reserved() / (1024**2), 1)

            completed_steps = step
            should_stop_early = stop_after_first_update and optimizer_updates >= 1
            logger.record(
                event="train_step",
                step=step,
                total_steps=planned_steps,
                loss=round(step_loss_value, 6),
                learning_rate=config.learning_rate,
                grad_norm=round(grad_norm_value, 6),
                reward_mean=score_summary["reward_mean"] if score_summary["reward_mean"] is not None else 0.0,
                reward_std=round(reward_std, 6),
                relevance_mean=(
                    score_summary["relevance_mean"] if score_summary["relevance_mean"] is not None else 0.0
                ),
                grounding_mean=(
                    score_summary["grounding_mean"] if score_summary["grounding_mean"] is not None else 0.0
                ),
                uncertainty_mean=(
                    score_summary["uncertainty_mean"] if score_summary["uncertainty_mean"] is not None else 0.0
                ),
                kl_mean=round(sum(step_kl_values) / len(step_kl_values), 6) if step_kl_values else 0.0,
                completion_words_mean=(
                    round(sum(word_counts) / len(word_counts), 2) if word_counts else 0.0
                ),
                valid_completions=len(valid_completions),
                invalid_completions=step_invalid,
                tied_groups=1 if is_tied else 0,
                tied_group_rate=1.0 if is_tied else 0.0,
                step_updated=step_updated,
                optimizer_updates=optimizer_updates,
                rollout_seconds=round(rollout_seconds, 4),
                judge_seconds=round(judge_seconds, 4),
                step_seconds=round(time.perf_counter() - step_t0, 4),
                cuda_allocated_mib=cuda_alloc,
                cuda_reserved_mib=cuda_res,
            )

            should_eval = (
                step % effective_eval_steps == 0
                or step == planned_steps
                or should_stop_early
            )
            if should_eval:
                val_metrics = _evaluate_validation_prompts(
                    model,
                    tokenizer,
                    active_val_prompts,
                    judge,
                    profile,
                    hardware,
                )
                selection_val = float(val_metrics["val_selection_reward"])
                eligible_for_best = optimizer_updates >= 1 or not require_update
                is_best = False
                if eligible_for_best and (best_val_reward is None or selection_val > best_val_reward):
                    best_val_reward = selection_val
                    best_step = step
                    best_policy_snapshot = _snapshot_tensors(policy_params)
                    is_best = True
                logger.record(
                    event="eval",
                    step=step,
                    total_steps=planned_steps,
                    val_reward_mean=round(float(val_metrics["val_reward_mean"]), 6),
                    val_selection_reward=round(selection_val, 6),
                    val_relevance_mean=round(float(val_metrics["val_relevance_mean"]), 6),
                    val_grounding_mean=round(float(val_metrics["val_grounding_mean"]), 6),
                    val_uncertainty_mean=round(float(val_metrics["val_uncertainty_mean"]), 6),
                    val_scored_count=int(val_metrics["val_scored_count"]),
                    val_invalid_completions=int(val_metrics["val_invalid_completions"]),
                    best_step=best_step,
                    is_best=is_best,
                )
                save_figure(plot_grpo_diagnostics(logger.records), diagnostics_path)

            if should_stop_early:
                break

        save_figure(plot_grpo_diagnostics(logger.records), diagnostics_path)
    except Exception:
        if logger.records:
            save_figure(plot_grpo_diagnostics(logger.records), diagnostics_path)
        raise

    if _max_tensor_delta(ref_params, initial_ref_snapshot) > 0.0:
        raise RuntimeError("Frozen SFT reference adapter ('sft_ref') weights mutated during GRPO.")

    if best_policy_snapshot is not None:
        _restore_tensors(policy_params, best_policy_snapshot)

    final_policy_delta = _max_tensor_delta(policy_params, initial_policy_snapshot)
    if require_update and (optimizer_updates < 1 or final_policy_delta <= 0.0):
        raise RuntimeError(
            "GRPO completed without demonstrating a trainable policy update "
            f"(optimizer_updates={optimizer_updates}, tied_groups={total_tied_groups}, "
            f"invalid_completions={total_invalid_completions})."
        )

    adapter_dir = output / "adapter"
    lineage = {
        "version": 1,
        "stage": "grpo",
        "source_sft_adapter": display_path(sft_dir),
        "source_sft_run": display_path(sft_run_dir) if sft_run_dir is not None else None,
        "source_sft_fingerprint": source_sft_fp,
        "reference_adapter_name": REFERENCE_ADAPTER_NAME,
        "dataset_sha256": dataset_sha256,
        "split_sha256": split_sha256,
        "seed": seed,
        "smoke": smoke,
        "completed_steps": completed_steps,
        "optimizer_updates": optimizer_updates,
        "tied_groups": total_tied_groups,
        "invalid_completions": total_invalid_completions,
        "max_policy_param_delta": final_policy_delta,
        "best_validation_step": best_step,
        "best_validation_reward": best_val_reward,
        "hyperparameters": asdict(config),
        "judge": judge.provenance(),
    }
    _save_policy_adapter(model, adapter_dir, profile, lineage)

    if adapter_fingerprint(sft_dir) != source_sft_fp:
        raise RuntimeError("Source SFT adapter files were modified during GRPO training.")

    return GRPOFitResult(
        adapter_dir=adapter_dir,
        lineage_file=adapter_dir / "grpo-lineage.json",
        metrics_file=metrics_path,
        diagnostics_plot=diagnostics_path,
        history=logger.records,
        lineage=lineage,
    )


__all__ = [
    "ADVANTAGE_EPS",
    "POLICY_ADAPTER_NAME",
    "REFERENCE_ADAPTER_NAME",
    "GRPOConfig",
    "GRPOFitResult",
    "activate_adapter",
    "compute_group_advantages",
    "fit_grpo",
    "load_policy_with_sft_reference",
]
