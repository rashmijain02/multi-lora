"""Paired held-out evaluation, comparison identity checks, and sample formatting."""

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from .data import ReplyPair
from .monitoring import plot_losses
from .paths import (
    create_stage_run_dir,
    display_path,
    ensure_unlinked_path,
)
from .prompts import (
    INSTRUCTION,
    Hardware,
    ModelProfile,
    Prompt,
    end_id,
    prepare_prompt,
    supervised_example,
)

EVALUATION_DECODING = {"do_sample": False}


@dataclass(frozen=True)
class EvaluationCase:
    pair: ReplyPair
    prompt: Prompt
    reference: dict[str, list[int]] | None


def prepare_evaluation(
    rows: list[ReplyPair],
    tokenizer,
    profile: ModelProfile,
    hardware: Hardware,
) -> list[EvaluationCase]:
    cases = []
    for pair in rows:
        prompt = prepare_prompt(tokenizer, hardware, pair.conversation)
        reference = supervised_example(tokenizer, profile, hardware, prompt, pair.reply)
        cases.append(EvaluationCase(pair, prompt, reference))
    return cases


def evaluate(cases: list[EvaluationCase], generate, reference_loss) -> tuple[dict, list[str | None]]:
    drafts: list[str | None] = []
    failures = 0
    total_loss = 0.0
    reference_tokens = 0
    reference_rows = 0
    for case in cases:
        try:
            draft = generate(case.prompt.ids).strip()
        except RuntimeError as err:
            if "out of memory" in str(err).lower():
                raise
            draft = None
            failures += 1
        drafts.append(draft)
        if case.reference is not None:
            tokens = sum(label != -100 for label in case.reference["labels"])
            loss = reference_loss(case.reference)
            if not math.isfinite(loss):
                raise ValueError("Held-out reference loss is not finite.")
            reference_rows += 1
            reference_tokens += tokens
            total_loss += tokens * loss
    sizes = [len(draft.split()) for draft in drafts if draft]
    return {
        "holdout_rows": len(cases),
        "truncated_inputs": sum(case.prompt.truncated for case in cases),
        "valid_drafts": len(sizes),
        "generation_failures": failures,
        "empty_drafts": sum(draft == "" for draft in drafts),
        "mean_reply_words": sum(sizes) / len(sizes) if sizes else None,
        "reference_rows": reference_rows,
        "reference_tokens": reference_tokens,
        "reference_token_loss": total_loss / reference_tokens if reference_tokens else None,
    }, drafts


def evaluate_model(model, tokenizer, cases: list[EvaluationCase], profile: ModelProfile, hardware: Hardware):
    import torch

    model.eval()
    stop = end_id(tokenizer, profile)
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else stop
    dev = getattr(model, "device", None)
    use_cuda_batch = (
        isinstance(dev, torch.device)
        and dev.type == "cuda"
        and len(cases) > 1
    )

    if use_cuda_batch:
        drafts: list[str | None] = [None] * len(cases)
        failures = 0
        ordered = sorted(range(len(cases)), key=lambda idx: len(cases[idx].prompt.ids))
        torch.cuda.empty_cache()
        free_bytes, _ = torch.cuda.mem_get_info(dev)
        free_mib = free_bytes / (1024**2)
        batch_size = 6 if free_mib >= 7500 else 3
        cleared_long_cache = False
        cursor = 0
        while cursor < len(ordered):
            probe_len = len(cases[ordered[cursor]].prompt.ids)
            if probe_len > 1024:
                eff_bs = min(batch_size, 2)
            elif probe_len > 512:
                eff_bs = min(batch_size, 3)
            else:
                eff_bs = batch_size
            if probe_len > 512 and not cleared_long_cache:
                torch.cuda.empty_cache()
                cleared_long_cache = True
            chunk_idx = ordered[cursor : cursor + eff_bs]
            max_len = max(len(cases[i].prompt.ids) for i in chunk_idx)
            padded = [
                [pad] * (max_len - len(cases[i].prompt.ids)) + list(cases[i].prompt.ids)
                for i in chunk_idx
            ]
            masks = [
                [0] * (max_len - len(cases[i].prompt.ids)) + [1] * len(cases[i].prompt.ids)
                for i in chunk_idx
            ]
            try:
                inputs = torch.tensor(padded, dtype=torch.long, device=dev)
                attn = torch.tensor(masks, dtype=torch.long, device=dev)
                with torch.inference_mode():
                    tokens = model.generate(
                        input_ids=inputs,
                        attention_mask=attn,
                        max_new_tokens=hardware.completion_tokens,
                        do_sample=False,
                        eos_token_id=stop,
                        pad_token_id=pad,
                    )
                for row_pos, orig_i in enumerate(chunk_idx):
                    text = tokenizer.decode(
                        tokens[row_pos, max_len:],
                        skip_special_tokens=True,
                    ).strip()
                    drafts[orig_i] = text
                cursor += len(chunk_idx)
            except RuntimeError as err:
                if "out of memory" in str(err).lower() and batch_size > 1:
                    torch.cuda.empty_cache()
                    batch_size = max(1, batch_size // 2)
                    continue
                if "out of memory" in str(err).lower():
                    raise
                for orig_i in chunk_idx:
                    try:
                        single = torch.tensor([cases[orig_i].prompt.ids], dtype=torch.long, device=dev)
                        with torch.inference_mode():
                            tok_out = model.generate(
                                input_ids=single,
                                attention_mask=torch.ones_like(single),
                                max_new_tokens=hardware.completion_tokens,
                                do_sample=False,
                                eos_token_id=stop,
                                pad_token_id=pad,
                            )
                        drafts[orig_i] = tokenizer.decode(
                            tok_out[0, len(cases[orig_i].prompt.ids) :],
                            skip_special_tokens=True,
                        ).strip()
                    except RuntimeError as inner_err:
                        if "out of memory" in str(inner_err).lower():
                            raise
                        drafts[orig_i] = None
                        failures += 1
                cursor += len(chunk_idx)

        torch.cuda.empty_cache()
        total_loss = 0.0
        reference_tokens = 0
        reference_rows = 0
        for case in cases:
            if case.reference is not None:
                ref_toks = sum(label != -100 for label in case.reference["labels"])
                inp = torch.tensor([case.reference["input_ids"]], device=dev)
                lbl = torch.tensor([case.reference["labels"]], device=dev)
                with torch.inference_mode():
                    loss = model(input_ids=inp, labels=lbl, use_cache=False).loss.item()
                if not math.isfinite(loss):
                    raise ValueError("Held-out reference loss is not finite.")
                reference_rows += 1
                reference_tokens += ref_toks
                total_loss += ref_toks * loss

        sizes = [len(d.split()) for d in drafts if d]
        return {
            "holdout_rows": len(cases),
            "truncated_inputs": sum(case.prompt.truncated for case in cases),
            "valid_drafts": len(sizes),
            "generation_failures": failures,
            "empty_drafts": sum(d == "" for d in drafts),
            "mean_reply_words": sum(sizes) / len(sizes) if sizes else None,
            "reference_rows": reference_rows,
            "reference_tokens": reference_tokens,
            "reference_token_loss": total_loss / reference_tokens if reference_tokens else None,
        }, drafts

    def generate(ids):
        inputs = torch.tensor([ids], device=model.device)
        with torch.inference_mode():
            tokens = model.generate(
                input_ids=inputs,
                attention_mask=torch.ones_like(inputs),
                max_new_tokens=hardware.completion_tokens,
                do_sample=False,
                eos_token_id=stop,
                pad_token_id=pad,
            )
        return tokenizer.decode(tokens[0, len(ids) :], skip_special_tokens=True)

    def reference_loss(row):
        inputs = torch.tensor([row["input_ids"]], device=model.device)
        labels = torch.tensor([row["labels"]], device=model.device)
        with torch.inference_mode():
            return model(input_ids=inputs, labels=labels, use_cache=False).loss.item()

    return evaluate(cases, generate, reference_loss)


def build_comparison_identity(
    *,
    dataset_sha256: str,
    split_sha256: str,
    holdout_lines: list[int],
    profile: ModelProfile,
    hardware: Hardware,
    instruction: str = INSTRUCTION,
) -> dict:
    return {
        "version": 1,
        "partition": "holdout",
        "dataset_sha256": dataset_sha256,
        "split_sha256": split_sha256,
        "holdout_lines": list(holdout_lines),
        "base_model": profile.model_id,
        "revision": profile.revision,
        "end_token": profile.end_token,
        "prompt_budget": {
            "max_length": hardware.max_length,
            "completion_tokens": hardware.completion_tokens,
        },
        "instruction_sha256": hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        "decoding": dict(EVALUATION_DECODING),
    }


def validate_comparison_identity(expected: dict, candidate_summary: object, *, label: str) -> None:
    if type(candidate_summary) is not dict:
        raise ValueError(f"Saved {label} summary is not a JSON object.")
    actual = candidate_summary.get("comparison_identity")
    if type(actual) is not dict:
        raise ValueError(f"Saved {label} summary does not contain comparison_identity provenance.")
    checks = (
        ("dataset_sha256", "dataset SHA-256"),
        ("split_sha256", "split manifest"),
        ("partition", "evaluation partition"),
        ("holdout_lines", "held-out case list"),
        ("base_model", "base model"),
        ("revision", "base model revision"),
        ("end_token", "end-of-turn token"),
        ("prompt_budget", "prompt/completion token budget"),
        ("instruction_sha256", "system instruction"),
        ("decoding", "evaluation decoding settings"),
    )
    for key, description in checks:
        if actual.get(key) != expected.get(key):
            raise ValueError(
                f"Incompatible saved {label} comparison: {description} mismatch "
                f"(expected {expected.get(key)!r}, got {actual.get(key)!r})."
            )


def load_saved_stage_summary(
    path: str | Path,
    expected_identity: dict,
    *,
    label: str,
    expected_stage: str | None = None,
    cwd: Path | None = None,
) -> tuple[Path, dict]:
    raw = Path(str(path).strip())
    base = ensure_unlinked_path(cwd if cwd is not None else Path.cwd())
    target = ensure_unlinked_path(raw if raw.is_absolute() else (base / raw))
    if not target.exists():
        raise ValueError(f"Saved {label} path does not exist: {display_path(target)}")
    if target.is_dir():
        run_dir = target
        summary_path = ensure_unlinked_path(target / "summary.json")
    else:
        summary_path = target
        run_dir = target.parent
    if not summary_path.is_file():
        raise ValueError(f"Saved {label} summary.json not found at: {display_path(summary_path)}")
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except ValueError as err:
        raise ValueError(f"Saved {label} summary is not valid JSON: {err}") from err
    if expected_stage is not None and isinstance(payload, dict):
        actual_stage = payload.get("stage")
        if actual_stage is not None and actual_stage != expected_stage:
            raise ValueError(
                f"Saved {label} summary has stage {actual_stage!r}, expected {expected_stage!r}."
            )
    validate_comparison_identity(expected_identity, payload, label=label)
    return run_dir, payload


def save_baseline_run(
    output_root: Path,
    *,
    evaluation: dict,
    comparison_identity: dict,
    profile: ModelProfile,
    hardware: Hardware,
    heldout: list[EvaluationCase],
    drafts: list[str | None],
    smoke: bool = False,
    show_private: bool = False,
    sample_count: int = 3,
    seed: int = 42,
    input_dir: Path | None = None,
    dataset: dict | None = None,
) -> tuple[Path, Path | None]:
    run_dir = create_stage_run_dir(output_root, "baseline", smoke=smoke)
    samples = sample_drafts(
        heldout,
        drafts,
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
                    stage_note="Stage: unadapted prompt-only baseline",
                )
            )
    summary: dict[str, object] = {
        "stage": "baseline",
        "smoke": smoke,
        "seed": seed,
        "instruction": INSTRUCTION,
        "note": "reference_token_loss measures fit to the archived reply, not factual correctness.",
        "input_dir": display_path(input_dir) if input_dir is not None else None,
        "output_root": display_path(output_root),
        "run_dir": display_path(run_dir),
        "samples_file": display_path(samples_file) if samples_file is not None else None,
        "model": asdict(profile),
        "hardware": asdict(hardware),
    }
    if dataset is not None:
        summary["dataset"] = dataset
    summary["comparison_identity"] = comparison_identity
    summary["evaluation"] = evaluation
    summary["baseline"] = evaluation
    with (run_dir / "summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    return run_dir, samples_file


def sample_drafts(
    cases: list[EvaluationCase],
    baseline: list[str | None],
    adapted: list[str | None] | None = None,
    *,
    grpo: list[str | None] | None = None,
    show_private: bool = False,
    seed: int = 42,
    count: int = 3,
) -> list[dict]:
    if not show_private:
        return []
    if len(cases) != len(baseline):
        raise ValueError("All compared runs must cover the same ordered holdout.")
    if adapted is not None and len(cases) != len(adapted):
        raise ValueError("Both runs must cover the same ordered holdout.")
    if grpo is not None and len(cases) != len(grpo):
        raise ValueError("All compared runs must cover the same ordered holdout.")
    indices = sorted(random.Random(seed).sample(range(len(cases)), min(count, len(cases))))
    results: list[dict] = []
    for index in indices:
        row: dict = {
            "line": cases[index].pair.line,
            "conversation_shown": cases[index].prompt.conversation,
            "baseline": baseline[index],
        }
        if adapted is not None:
            row["fine_tuned"] = adapted[index]
        if grpo is not None:
            row["grpo"] = grpo[index]
        row["reference"] = cases[index].pair.reply
        results.append(row)
    return results


def format_samples(
    samples: list[dict],
    profile: ModelProfile,
    hardware: Hardware,
    *,
    dataset_label: str,
    stage_note: str,
) -> str:
    base_label = f"{profile.model_id} @ {profile.revision}" if profile.revision else profile.model_id
    lines = [
        "Email reply drafting - held-out comparisons",
        f"Base model: {base_label}",
        f"{stage_note}. Max reply tokens: {hardware.completion_tokens}.",
        f"Dataset line numbers refer to {dataset_label}.",
        "Reference-token loss measures fit to the archived reply, not factual correctness.",
    ]
    for index, sample in enumerate(samples, 1):
        reference = sample["reference"]
        baseline = sample["baseline"] if sample["baseline"] is not None else "[generation failed]"
        lines += [
            "",
            "=" * 72,
            f"Example {index} | Dataset line {sample['line']} | Reference: {len(reference.split())} words",
            "",
            "CONVERSATION (INPUT TO MODELS)",
            sample["conversation_shown"],
            "",
            "PROMPT-ONLY BASELINE",
            baseline,
        ]
        if "fine_tuned" in sample:
            tuned = sample["fine_tuned"] if sample["fine_tuned"] is not None else "[generation failed]"
            lines += ["", "SFT DRAFT", tuned]
        if "grpo" in sample:
            grpo_draft = sample["grpo"] if sample["grpo"] is not None else "[generation failed]"
            lines += ["", "GRPO DRAFT", grpo_draft]
        lines += [
            "",
            "REFERENCE (ARCHIVED SENT REPLY)",
            reference,
        ]
    return "\n".join(lines) + "\n"


__all__ = [
    "EVALUATION_DECODING",
    "EvaluationCase",
    "build_comparison_identity",
    "evaluate",
    "evaluate_model",
    "format_samples",
    "load_saved_stage_summary",
    "plot_losses",
    "prepare_evaluation",
    "sample_drafts",
    "save_baseline_run",
    "validate_comparison_identity",
]
