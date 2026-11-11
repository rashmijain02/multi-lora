"""Tools for the fictional Leadership Evidence Lab workshop."""

from .baseline import fit_baseline, fit_lexical_baseline, predict_baseline
from .config import ModelConfig, load_config
from .data import MECHANISMS, DatasetError, load_dataset, split_records
from .dataset import Example, Label, validate_examples
from .evaluation import EvaluationReport, evaluate, evaluate_predictions
from .inference import GenerationResult, generate_predictions
from .schema import build_prompt, parse_model_output
from .training import train_lora

__all__ = [
    "MECHANISMS",
    "DatasetError",
    "EvaluationReport",
    "Example",
    "GenerationResult",
    "Label",
    "ModelConfig",
    "build_prompt",
    "evaluate",
    "evaluate_predictions",
    "fit_baseline",
    "fit_lexical_baseline",
    "generate_predictions",
    "load_config",
    "load_dataset",
    "parse_model_output",
    "predict_baseline",
    "split_records",
    "train_lora",
    "validate_examples",
]
