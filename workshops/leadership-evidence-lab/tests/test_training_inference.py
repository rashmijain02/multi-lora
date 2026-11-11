from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from empathy_lab.config import ModelConfig
from empathy_lab.data import as_examples, load_dataset, split_records
from empathy_lab.inference import generate_predictions
from empathy_lab.training import _training_dataset


@pytest.mark.parametrize("launch", ["repository", "workshop", "notebooks"])
def test_training_notebook_uses_a_relative_destination_from_its_selected_root(
    monkeypatch: pytest.MonkeyPatch, launch: str
) -> None:
    from empathy_lab import modeling

    workshop = Path(__file__).resolve().parents[1]
    cwd = {
        "repository": workshop.parents[1],
        "workshop": workshop,
        "notebooks": workshop / "notebooks",
    }[launch]
    monkeypatch.chdir(cwd)
    notebook = json.loads((workshop / "notebooks" / "02_manual_training.ipynb").read_text())
    cells = {cell["id"]: "".join(cell["source"]) for cell in notebook["cells"]}
    namespace: dict = {}
    exec(cells["setup"], namespace)  # noqa: S102 - Exercise the checked-in notebook source.
    namespace.update(RUN_TRAINING=True, config=object(), training=[], validation=[])
    called = []

    def capture_train(config, training, validation, destination):
        assert Path.cwd() == workshop
        assert not destination.is_absolute() and ".." not in destination.parts
        assert Path.cwd() / destination == namespace["ARTIFACTS"] / "adapter"
        called.append(destination)

    monkeypatch.setattr(modeling, "train", capture_train)
    exec(cells["training"], namespace)  # noqa: S102 - Exercise the checked-in notebook source.
    assert len(called) == 1
    assert Path.cwd() == cwd


class TinyTokenizer:
    pad_token_id = 0
    eos_token_id = 6
    padding_side = "right"

    def __call__(self, value: str, **kwargs: object) -> dict[str, list[int]]:
        if isinstance(value, list):
            batch = [[1, 2, 3] for _ in value]
            return {
                "input_ids": torch.tensor(batch),
                "attention_mask": torch.ones((len(batch), 3), dtype=torch.long),
            }
        if value.startswith("Assess only"):
            return {"input_ids": [1, 2, 3]}
        return {"input_ids": [4, 5]}

    def decode(self, tokens: object, **kwargs: object) -> str:
        return "not JSON"


def test_completion_only_dataset_masks_prompt_tokens() -> None:
    records = split_records(load_dataset())["train"]
    examples = as_examples(records[:1])
    dataset, collator = _training_dataset(
        examples, TinyTokenizer(), max_length=32, model_id="test-model"
    )

    item = dataset[0]
    assert item["labels"] == [-100, -100, -100, 4, 5, 6]
    batch = collator([item])
    assert batch["input_ids"].tolist() == [[1, 2, 3, 4, 5, 6]]
    assert batch["labels"].tolist() == [[-100, -100, -100, 4, 5, 6]]


def test_completion_dataset_rejects_overlength_without_truncating_supervision() -> None:
    examples = as_examples(split_records(load_dataset())["train"][:1])
    with pytest.raises(ValueError, match="no text was truncated"):
        _training_dataset(examples, TinyTokenizer(), max_length=5, model_id="test-model")


def test_native_template_options_apply_to_legacy_training_and_inference_prompts() -> None:
    from empathy_lab.schema import render_prompt

    class ChatTokenizer(TinyTokenizer):
        def apply_chat_template(self, messages: list, **kwargs: object) -> str:
            assert messages[0]["role"] == "user"
            assert kwargs["enable_thinking"] is False
            return messages[0]["content"]

    example = as_examples(split_records(load_dataset())["train"][:1])[0]
    tokenizer = ChatTokenizer()
    options = {"enable_thinking": False}
    assert render_prompt(example, "nemotron-test", tokenizer, options).startswith("Assess only")
    dataset, _ = _training_dataset([example], tokenizer, 32, "nemotron-test", options)
    assert dataset[0]["labels"][:3] == [-100, -100, -100]


class TinyModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.marker = torch.nn.Parameter(torch.zeros(1))

    def generate(self, input_ids: torch.Tensor, **kwargs: object) -> torch.Tensor:
        token = torch.full(
            (input_ids.shape[0], 1),
            7,
            dtype=input_ids.dtype,
            device=input_ids.device,
        )
        return torch.cat((input_ids, token), dim=1)


def test_invalid_generation_is_preserved_instead_of_scored() -> None:
    records = split_records(load_dataset())["test"][:2]
    config = ModelConfig(
        model_id="local/test-model",
        revision="a" * 40,
        device="cpu",
        dtype="float32",
        batch_size=2,
    )
    results = generate_predictions(
        as_examples(records),
        config,
        model=TinyModel(),
        tokenizer=TinyTokenizer(),
    )

    assert len(results) == 2
    assert all(not result.valid for result in results)
    assert all(result.scores is None and result.invalid_reason for result in results)
