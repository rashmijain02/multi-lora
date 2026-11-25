"""Local-only training/validation telemetry (metrics.jsonl) and headless visualizations."""

import json
import math
import time
from collections.abc import Callable
from pathlib import Path

FORBIDDEN_TEXT_KEYS = frozenset({
    "conversation",
    "conversation_shown",
    "reply",
    "reference",
    "draft",
    "drafts",
    "prompt",
    "completion",
    "completions",
    "text",
    "body",
    "raw_response",
    "messages",
    "samples",
})
ALLOWED_STRING_KEYS = frozenset({"stage", "event", "checkpoint"})


def resolve_eval_steps(eval_steps: int | None, *, total_steps: int, smoke: bool = False) -> int:
    if eval_steps is not None and eval_steps < 1:
        raise ValueError("--eval-steps must be a positive integer.")
    bounded_total = max(1, total_steps)
    if smoke:
        return 1 if eval_steps is None else min(eval_steps, bounded_total)
    if eval_steps is None:
        return min(50, max(1, bounded_total // 4 or 1))
    return min(eval_steps, bounded_total)


def cuda_memory_mib(torch_mod: object | None) -> tuple[float | None, float | None]:
    cuda = getattr(torch_mod, "cuda", None)
    if cuda is None:
        return None, None
    try:
        is_avail = cuda.is_available() if callable(getattr(cuda, "is_available", None)) else True
        if not is_avail:
            return None, None
        alloc = float(cuda.memory_allocated()) / 2**20
        reserved = float(cuda.memory_reserved()) / 2**20
        return round(alloc, 1), round(reserved, 1)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None, None


def sanitize_metric_entry(entry: dict) -> dict:
    clean: dict[str, int | float | bool | str | None] = {}
    for key, value in entry.items():
        if not isinstance(key, str) or key in FORBIDDEN_TEXT_KEYS:
            raise ValueError(f"Telemetry key '{key}' is prohibited to prevent private text leakage.")
        if value is None or isinstance(value, (bool, int)):
            clean[key] = value
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"Telemetry metric '{key}' must be finite, got {value}.")
            clean[key] = round(value, 6)
        elif isinstance(value, str):
            if key not in ALLOWED_STRING_KEYS or len(value) > 128 or "\n" in value:
                raise ValueError(
                    f"String telemetry field '{key}' is not allowlisted; raw text is prohibited."
                )
            clean[key] = value
        else:
            raise ValueError(f"Unsupported telemetry value type for '{key}': {type(value).__name__}")
    return clean


def format_progress_line(entry: dict) -> str:
    stage = entry.get("stage", "train")
    event = entry.get("event", "step")
    step = entry.get("step", "?")
    total = entry.get("total_steps")
    step_label = f"{step}/{total}" if total else str(step)
    if stage == "sft" and event == "train_step":
        parts = [f"[sft step {step_label}]"]
        if entry.get("loss") is not None:
            parts.append(f"loss={entry['loss']:.4f}")
        if entry.get("learning_rate") is not None:
            parts.append(f"lr={entry['learning_rate']:.2e}")
        if entry.get("grad_norm") is not None:
            parts.append(f"grad_norm={entry['grad_norm']:.3f}")
        if entry.get("step_seconds") is not None:
            parts.append(f"dt={entry['step_seconds']:.2f}s")
        if entry.get("cuda_allocated_mib") is not None:
            parts.append(f"vram={entry['cuda_allocated_mib']:.1f}MiB")
        return " ".join(parts)
    if stage == "sft" and event == "eval":
        best = entry.get("best_step")
        suffix = f" best_step={best}" if best is not None else ""
        return f"[sft eval step {step_label}] eval_loss={entry['eval_loss']:.4f}{suffix}"
    if stage == "grpo" and event == "train_step":
        parts = [f"[grpo step {step_label}]"]
        if entry.get("reward_mean") is not None:
            std = entry.get("reward_std", 0.0) or 0.0
            parts.append(f"reward={entry['reward_mean']:.4f}+/-{std:.4f}")
        dims = [
            f"{short}={entry[key]:.2f}"
            for short, key in (
                ("rel", "relevance_mean"),
                ("gnd", "grounding_mean"),
                ("unc", "uncertainty_mean"),
            )
            if entry.get(key) is not None
        ]
        if dims:
            parts.append(f"({' '.join(dims)})")
        if entry.get("kl_mean") is not None:
            parts.append(f"kl={entry['kl_mean']:.4f}")
        if entry.get("tied_groups") is not None:
            parts.append(f"tied={entry['tied_groups']}")
        if entry.get("invalid_completions") is not None:
            parts.append(f"invalid={entry['invalid_completions']}")
        if entry.get("rollout_seconds") is not None and entry.get("judge_seconds") is not None:
            parts.append(f"rollout={entry['rollout_seconds']:.2f}s judge={entry['judge_seconds']:.2f}s")
        return " ".join(parts)
    if stage == "grpo" and event == "eval":
        best = entry.get("best_step")
        suffix = f" best_step={best}" if best is not None else ""
        return f"[grpo eval step {step_label}] val_reward={entry['val_reward_mean']:.4f}{suffix}"
    return f"[{stage} {event} step {step_label}]"


class MetricsLogger:
    """Append-only JSONL telemetry writer with immediate disk flush and progress callbacks."""

    def __init__(
        self,
        path: Path,
        *,
        stage: str,
        notify: Callable[[str], None] | None = None,
    ) -> None:
        if path.resolve() != path.absolute():
            raise ValueError("Telemetry file path must not use symbolic links or junctions.")
        self.path = path
        self.stage = stage
        self._notify = notify or (lambda _: None)
        self.records: list[dict] = []
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def record(self, *, emit_progress: bool = True, **fields) -> dict:
        payload = sanitize_metric_entry({"stage": self.stage, **fields})
        line = json.dumps(payload, sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
        self.records.append(payload)
        if emit_progress and payload.get("event") in ("train_step", "eval"):
            self._notify(format_progress_line(payload))
        return payload


def read_metrics(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            stripped = raw.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def save_figure(fig, path: Path) -> Path:
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    FigureCanvasAgg(fig)
    fig.savefig(path, format="png", dpi=140, bbox_inches="tight")
    return path


def _best_sft_eval_point(records: list[dict]) -> tuple[int, float] | None:
    eval_points = [
        (int(row["step"]), float(row["eval_loss"]))
        for row in records
        if "eval_loss" in row and row.get("eval_loss") is not None and "step" in row
    ]
    if not eval_points:
        return None
    return min(eval_points, key=lambda item: item[1])


def plot_losses(history: list[dict]):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(6.4, 4.0))
    axis = fig.subplots()
    plotted = False
    for key, name in (("loss", "Training"), ("eval_loss", "Validation")):
        points = [(row["step"], row[key]) for row in history if key in row and row[key] is not None]
        if points:
            axis.plot(*zip(*points), marker=".", label=name)
            plotted = True
    best = _best_sft_eval_point(history)
    if best is not None:
        axis.axvline(best[0], linestyle="--", alpha=0.5, color="tab:green", label=f"Best val (step {best[0]})")
        axis.scatter([best[0]], [best[1]], color="tab:green", zorder=5)
        plotted = True
    axis.set(xlabel="Optimizer step", ylabel="Reply token loss", title="SFT Reply-Token Loss")
    axis.grid(True, alpha=0.25)
    if plotted:
        axis.legend()
    return fig


def plot_sft_diagnostics(records: list[dict]):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(11.0, 7.5))
    axes = fig.subplots(2, 2)
    fig.suptitle("SFT Training & Periodic Validation Diagnostics")

    ax_loss, ax_lr = axes[0]
    ax_grad, ax_sys = axes[1]

    train_loss = [(r["step"], r["loss"]) for r in records if r.get("loss") is not None and "step" in r]
    val_loss = [(r["step"], r["eval_loss"]) for r in records if r.get("eval_loss") is not None and "step" in r]
    if train_loss:
        ax_loss.plot(*zip(*train_loss), marker=".", label="Train loss")
    if val_loss:
        ax_loss.plot(*zip(*val_loss), marker="o", label="Validation loss")
    best = _best_sft_eval_point(records)
    if best is not None:
        ax_loss.axvline(best[0], linestyle="--", alpha=0.55, color="tab:green", label=f"Best ckpt (step {best[0]})")
    ax_loss.set(xlabel="Step", ylabel="Reply-token loss", title="Train vs. Validation Loss")
    ax_loss.grid(True, alpha=0.25)
    if train_loss or val_loss:
        ax_loss.legend()

    lr_pts = [(r["step"], r["learning_rate"]) for r in records if r.get("learning_rate") is not None and "step" in r]
    if lr_pts:
        ax_lr.plot(*zip(*lr_pts), marker=".", color="tab:purple")
    ax_lr.set(xlabel="Step", ylabel="Learning rate", title="Learning Rate Schedule")
    ax_lr.grid(True, alpha=0.25)

    grad_pts = [(r["step"], r["grad_norm"]) for r in records if r.get("grad_norm") is not None and "step" in r]
    if grad_pts:
        ax_grad.plot(*zip(*grad_pts), marker=".", color="tab:red")
    ax_grad.set(xlabel="Step", ylabel="L2 norm", title="Gradient Norm")
    ax_grad.grid(True, alpha=0.25)

    mem_pts = [
        (r["step"], r["cuda_allocated_mib"])
        for r in records
        if r.get("cuda_allocated_mib") is not None and "step" in r
    ]
    dt_pts = [(r["step"], r["step_seconds"]) for r in records if r.get("step_seconds") is not None and "step" in r]
    if mem_pts:
        ax_sys.plot(*zip(*mem_pts), marker=".", color="tab:cyan", label="CUDA alloc (MiB)")
    elif dt_pts:
        ax_sys.plot(*zip(*dt_pts), marker=".", color="tab:brown", label="Step time (s)")
    ax_sys.set(
        xlabel="Step",
        ylabel="MiB" if mem_pts else "Seconds",
        title="CUDA Memory / Step Timing",
    )
    ax_sys.grid(True, alpha=0.25)
    if mem_pts or dt_pts:
        ax_sys.legend()

    fig.tight_layout()
    return fig


def plot_grpo_diagnostics(records: list[dict]):
    from matplotlib.figure import Figure

    fig = Figure(figsize=(11.5, 8.0))
    axes = fig.subplots(2, 2)
    fig.suptitle("GRPO Rollout, Judge Rubric & Validation Diagnostics")

    ax_rew, ax_dims = axes[0]
    ax_kl, ax_len = axes[1]

    train_rew = [r for r in records if r.get("event") == "train_step" and r.get("reward_mean") is not None]
    val_rew = [r for r in records if r.get("event") == "eval" and r.get("val_reward_mean") is not None]
    if train_rew:
        steps = [r["step"] for r in train_rew]
        means = [r["reward_mean"] for r in train_rew]
        stds = [r.get("reward_std") or 0.0 for r in train_rew]
        ax_rew.plot(steps, means, marker=".", label="Train reward (mean)")
        lower = [max(0.0, m - s) for m, s in zip(means, stds)]
        upper = [min(1.0, m + s) for m, s in zip(means, stds)]
        ax_rew.fill_between(steps, lower, upper, alpha=0.18, label="Train +/-1 std")
    if val_rew:
        v_steps = [r["step"] for r in val_rew]
        v_means = [r["val_reward_mean"] for r in val_rew]
        ax_rew.plot(v_steps, v_means, marker="o", label="Validation reward")
        best_idx = max(range(len(val_rew)), key=lambda idx: (v_means[idx], -v_steps[idx]))
        ax_rew.axvline(
            v_steps[best_idx],
            linestyle="--",
            alpha=0.55,
            color="tab:green",
            label=f"Best ckpt (step {v_steps[best_idx]})",
        )
    ax_rew.set(xlabel="Step", ylabel="Scalar reward [0, 1]", title="Total Judge Reward")
    ax_rew.grid(True, alpha=0.25)
    if train_rew or val_rew:
        ax_rew.legend()

    for key, val_key, label, color in (
        ("relevance_mean", "val_relevance_mean", "Relevance", "tab:blue"),
        ("grounding_mean", "val_grounding_mean", "Grounding", "tab:orange"),
        ("uncertainty_mean", "val_uncertainty_mean", "Uncertainty", "tab:green"),
    ):
        t_pts = [(r["step"], r[key]) for r in train_rew if r.get(key) is not None]
        v_pts = [(r["step"], r[val_key]) for r in val_rew if r.get(val_key) is not None]
        if t_pts:
            ax_dims.plot(*zip(*t_pts), marker=".", color=color, label=f"{label} (train)")
        if v_pts:
            ax_dims.plot(*zip(*v_pts), marker="o", linestyle="--", color=color, label=f"{label} (val)")
    ax_dims.set(xlabel="Step", ylabel="Rubric score [0, 4]", title="Per-Dimension Rubric Trajectories")
    ax_dims.grid(True, alpha=0.25)
    if train_rew or val_rew:
        ax_dims.legend(fontsize=8)

    kl_pts = [(r["step"], r["kl_mean"]) for r in train_rew if r.get("kl_mean") is not None]
    grad_pts = [(r["step"], r["grad_norm"]) for r in train_rew if r.get("grad_norm") is not None]
    if kl_pts:
        ax_kl.plot(*zip(*kl_pts), marker=".", color="tab:red", label="KL vs. SFT ref")
    if grad_pts:
        ax_kl.plot(*zip(*grad_pts), marker="x", linestyle=":", color="tab:purple", label="Grad norm")
    ax_kl.set(xlabel="Step", ylabel="Magnitude", title="SFT Reference KL & Optimization")
    ax_kl.grid(True, alpha=0.25)
    if kl_pts or grad_pts:
        ax_kl.legend()

    len_pts = [(r["step"], r["completion_words_mean"]) for r in train_rew if r.get("completion_words_mean") is not None]
    tied_pts = [(r["step"], r["tied_group_rate"] * 100.0) for r in train_rew if r.get("tied_group_rate") is not None]
    if len_pts:
        ax_len.plot(*zip(*len_pts), marker=".", color="tab:brown", label="Mean reply words")
    if tied_pts:
        ax_len.plot(*zip(*tied_pts), marker="s", linestyle="--", color="tab:gray", label="Tied groups (%)")
    ax_len.set(xlabel="Step", ylabel="Words / Percent", title="Completion Length & Tied Groups")
    ax_len.grid(True, alpha=0.25)
    if len_pts or tied_pts:
        ax_len.legend()

    fig.tight_layout()
    return fig


def plot_stage_comparison(stages: dict[str, dict]):
    from matplotlib.figure import Figure

    ordered = [
        (name, stages[name])
        for name in ("baseline", "sft", "grpo")
        if name in stages and isinstance(stages[name], dict)
    ]
    has_judge = any(
        isinstance(metrics.get("judge"), dict) and metrics["judge"].get("reward_mean") is not None
        for _, metrics in ordered
    )
    cols = 4 if has_judge else 3
    fig = Figure(figsize=(3.4 * cols, 4.2))
    axes = fig.subplots(1, cols)
    fig.suptitle("Held-Out Stage Comparison (aggregate diagnostics; not factual verification)")

    labels = [name.upper() for name, _ in ordered]
    colors = ["tab:gray", "tab:blue", "tab:green"][: len(ordered)]

    valid_rates = [
        100.0 * m.get("valid_drafts", 0) / max(1, m.get("holdout_rows", 1))
        for _, m in ordered
    ]
    axes[0].bar(labels, valid_rates, color=colors)
    axes[0].set(ylabel="Valid drafts (%)", ylim=(0, 105), title="Valid Draft Rate")
    axes[0].grid(True, axis="y", alpha=0.25)

    words_vals = [m.get("mean_reply_words") or 0.0 for _, m in ordered]
    axes[1].bar(labels, words_vals, color=colors)
    axes[1].set(ylabel="Mean words", title="Mean Reply Length")
    axes[1].grid(True, axis="y", alpha=0.25)

    loss_vals = [m.get("reference_token_loss") or 0.0 for _, m in ordered]
    axes[2].bar(labels, loss_vals, color=colors)
    axes[2].set(ylabel="NLL (fit diagnostic)", title="Reference-Token Loss")
    axes[2].grid(True, axis="y", alpha=0.25)

    if has_judge:
        rew_vals = [
            (m.get("judge") or {}).get("reward_mean") or 0.0
            for _, m in ordered
        ]
        axes[3].bar(labels, rew_vals, color=colors)
        axes[3].set(ylabel="Mean judge reward [0, 1]", ylim=(0, 1.05), title="Local Judge Reward")
        axes[3].grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    return fig


def build_sft_trainer_callback(
    logger: MetricsLogger,
    *,
    eval_steps: int,
    total_steps: int,
    run_dir: Path,
    torch_mod: object | None = None,
    base_cls: type = object,
):
    """Build a Hugging Face TrainerCallback recording incremental SFT telemetry and plots."""

    class _SFTMonitoringCallback(base_cls):
        def __init__(self) -> None:
            if base_cls is not object:
                super().__init__()
            self._step_started: float | None = None
            self.best_eval_loss: float | None = None
            self.best_step: int | None = None

        def on_step_begin(self, args, state, control, **kwargs):
            self._step_started = time.perf_counter()
            return control

        def on_step_end(self, args, state, control, **kwargs):
            max_steps = getattr(state, "max_steps", 0) or total_steps
            step = getattr(state, "global_step", 0)
            if max_steps > 0 and step >= max_steps and step % eval_steps != 0:
                control.should_evaluate = True
                control.should_save = True
            return control

        def on_log(self, args, state, control, logs=None, **kwargs):
            if not logs:
                return control
            step = int(getattr(state, "global_step", logs.get("step", 0)))
            max_steps = int(getattr(state, "max_steps", 0) or total_steps)
            epoch = logs.get("epoch")
            alloc_mib, reserved_mib = cuda_memory_mib(torch_mod)
            if "loss" in logs and logs["loss"] is not None:
                elapsed = (
                    round(time.perf_counter() - self._step_started, 4)
                    if self._step_started is not None
                    else None
                )
                logger.record(
                    event="train_step",
                    step=step,
                    total_steps=max_steps,
                    epoch=float(epoch) if epoch is not None else None,
                    loss=float(logs["loss"]),
                    learning_rate=(
                        float(logs["learning_rate"]) if logs.get("learning_rate") is not None else None
                    ),
                    grad_norm=float(logs["grad_norm"]) if logs.get("grad_norm") is not None else None,
                    step_seconds=elapsed,
                    cuda_allocated_mib=alloc_mib,
                    cuda_reserved_mib=reserved_mib,
                )
            if "eval_loss" in logs and logs["eval_loss"] is not None:
                val_loss = float(logs["eval_loss"])
                is_best = self.best_eval_loss is None or val_loss < self.best_eval_loss
                if is_best:
                    self.best_eval_loss = val_loss
                    self.best_step = step
                logger.record(
                    event="eval",
                    step=step,
                    total_steps=max_steps,
                    epoch=float(epoch) if epoch is not None else None,
                    eval_loss=val_loss,
                    eval_runtime=(
                        float(logs["eval_runtime"]) if logs.get("eval_runtime") is not None else None
                    ),
                    best_step=self.best_step,
                    is_best=is_best,
                    cuda_allocated_mib=alloc_mib,
                    cuda_reserved_mib=reserved_mib,
                )
                self._refresh_plots()
            return control

        def on_train_end(self, args, state, control, **kwargs):
            self._refresh_plots()
            return control

        def _refresh_plots(self) -> None:
            if not logger.records:
                return
            save_figure(plot_losses(logger.records), run_dir / "loss.png")
            save_figure(plot_sft_diagnostics(logger.records), run_dir / "training_metrics.png")

    return _SFTMonitoringCallback()
