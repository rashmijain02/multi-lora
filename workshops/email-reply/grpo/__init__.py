"""Checkpoint-initialized QLoRA GRPO and frozen local model judge for email replies."""

from .judge import (
    AGGREGATION_RULE,
    DEFAULT_JUDGE_MODEL_ID,
    RUBRIC_VERSION,
    SCORE_DIMENSIONS,
    JudgeBudgetError,
    JudgeConfigError,
    JudgeFailureError,
    JudgeProfile,
    JudgeScore,
    LocalJudge,
    build_judge_messages,
    load_judge_model,
    parse_judge_response,
    summarize_judge_scores,
)
from .trainer import (
    POLICY_ADAPTER_NAME,
    REFERENCE_ADAPTER_NAME,
    GRPOConfig,
    GRPOFitResult,
    activate_adapter,
    compute_group_advantages,
    fit_grpo,
    load_policy_with_sft_reference,
)

__all__ = [
    "AGGREGATION_RULE",
    "DEFAULT_JUDGE_MODEL_ID",
    "POLICY_ADAPTER_NAME",
    "REFERENCE_ADAPTER_NAME",
    "RUBRIC_VERSION",
    "SCORE_DIMENSIONS",
    "GRPOConfig",
    "GRPOFitResult",
    "JudgeBudgetError",
    "JudgeConfigError",
    "JudgeFailureError",
    "JudgeProfile",
    "JudgeScore",
    "LocalJudge",
    "activate_adapter",
    "build_judge_messages",
    "compute_group_advantages",
    "fit_grpo",
    "load_judge_model",
    "load_policy_with_sft_reference",
    "parse_judge_response",
    "summarize_judge_scores",
]

