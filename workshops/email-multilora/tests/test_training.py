import json
from dataclasses import replace

import pytest

pytestmark = pytest.mark.training
torch = pytest.importorskip("torch")
pytest.importorskip("peft")

from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import PreTrainedTokenizerFast, Qwen2Config, Qwen2ForCausalLM

from email_workshop.data import ADAPTERS, load_splits
from email_workshop.evaluation import STRATEGIES, evaluate, score
from email_workshop.routing import fit_router
from email_workshop.serving import VllmBackend, concurrent_demo, vllm_command
from email_workshop.training import (
    CompletionCollator,
    LocalBackend,
    TrainConfig,
    train_adapter,
    training_example,
    verify_adapters,
)


@pytest.fixture
def tiny_base(tmp_path):
    vocabulary = {
        token: i
        for i, token in enumerate(
            [
                "[UNK]",
                "[PAD]",
                "[EOS]",
                "[BOS]",
                "system",
                "user",
                "assistant",
                "[",
                "]",
                '"',
                ",",
                "Business",
                "Reminders",
                "Finance",
                "&",
                "Bills",
                "subject",
                "body",
                "Classify",
                "email",
                "Please",
                "review",
                "details",
                "[]",
            ]
        )
    }
    raw = Tokenizer(WordLevel(vocabulary, unk_token="[UNK]"))
    raw.pre_tokenizer = Whitespace()
    tokenizer = PreTrainedTokenizerFast(
        tokenizer_object=raw,
        unk_token="[UNK]",
        pad_token="[PAD]",
        eos_token="[EOS]",
        bos_token="[BOS]",
        chat_template=(
            "{% for message in messages %}{{ message['role'] + ' ' + message['content'] + ' ' }}"
            "{% endfor %}{% if add_generation_prompt %}{{ 'assistant ' }}{% endif %}"
        ),
    )
    model = Qwen2ForCausalLM(
        Qwen2Config(
            vocab_size=len(vocabulary),
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=1,
            num_attention_heads=2,
            num_key_value_heads=2,
            max_position_embeddings=512,
            eos_token_id=2,
            pad_token_id=1,
        )
    )
    path = tmp_path / "tiny-random-qwen"
    model.save_pretrained(path)
    tokenizer.save_pretrained(path)
    return path, tokenizer


def test_completion_mask_and_negative_specialist(tiny_base):
    _, tokenizer = tiny_base
    row = {"subject": "Business", "body": "Business " * 1000, "labels": ["Business"]}
    example = training_example(tokenizer, row, "finance", 512)
    targets = [token for token in example["labels"] if token != -100]
    assert tokenizer.decode(targets, skip_special_tokens=True).replace(" ", "") == "[]"
    assert example["labels"][0] == -100
    assert len(example["input_ids"]) <= 512
    short = training_example(tokenizer, {**row, "body": "review"}, "generalist", 512)
    batch = CompletionCollator(tokenizer.pad_token_id)([example, short])
    assert batch["labels"][1, -1].item() == -100
    assert batch["attention_mask"][1, -1].item() == 0


def test_train_save_load_switch_and_manifest(prepared, tiny_base, monkeypatch):
    base, _ = tiny_base
    torch.set_num_threads(2)
    config = TrainConfig(
        model_id=str(base),
        model_revision="local-test",
        device="cpu",
        max_steps=1,
        sample_limit=4,
        gradient_accumulation=1,
    )
    for name in ADAPTERS:
        manifest = train_adapter(prepared, name, config)
        assert manifest["purpose"] == "smoke"
        assert manifest["metrics"]["train_loss"] > 0
        assert manifest["trainable_parameters"] < manifest["total_parameters"]
    manifests = verify_adapters(prepared)
    assert set(manifests) == set(ADAPTERS)
    backend = LocalBackend(prepared, device="cpu")
    assert set(backend.model.peft_config) == set(ADAPTERS)
    assert isinstance(backend.generate("Invoice", "Please review", "finance"), str)
    assert isinstance(backend.generate("Invoice", "Please review", "base"), str)
    heldout = load_splits(prepared)[0]["test"][:1]
    router, metadata = fit_router(prepared)
    for strategy in STRATEGIES:
        predictions = evaluate(
            heldout,
            backend,
            router,
            metadata,
            strategy,
            prepared / "smoke-evaluation" / f"{strategy}.json",
            "test",
        )
        assert score(predictions)[0]["rows"] == 1
    command = vllm_command(prepared, "artifacts/test")
    assert "--enable-lora" in command and "--lora-modules" in command
    assert all(any(arg.startswith(f"{name}=") for arg in command) for name in ADAPTERS)
    with pytest.raises(FileExistsError):
        train_adapter(prepared, "generalist", replace(config, epochs=3))
    with pytest.raises(ValueError, match="relative POSIX"):
        vllm_command(prepared, "../outside-workshop")
    with pytest.raises(ValueError, match="local"):
        VllmBackend(prepared, "https://external.example/v1")

    import requests

    def response(payload):
        result = requests.Response()
        result.status_code = 200
        result._content = json.dumps(payload).encode()
        return result

    def get(url, **kwargs):
        if url.endswith("/version"):
            return response({"version": "test-double"})
        return response({"data": [{"id": name} for name in ("email-base", *ADAPTERS)]})

    def post(url, **kwargs):
        assert url == "http://127.0.0.1:8000/v1/completions"
        payload = kwargs["json"]
        assert isinstance(payload["prompt"], list)
        assert len(payload["prompt"]) <= config.max_length - 128
        labels = {
            "operations": ["Business"],
            "finance": ["Finance & Bills"],
            "travel": ["Travel & Bookings"],
        }
        return response({"choices": [{"text": json.dumps(labels[payload["model"]])}]})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    serving = VllmBackend(prepared)
    assert serving.identity["server_version"] == "test-double"
    concurrent = concurrent_demo(serving, prepared / "synthetic-serving.json")
    assert {row["adapter"] for row in concurrent} == {"operations", "finance", "travel"}
    assert all(row["predicted"] for row in concurrent)
    weights = prepared / "adapters" / "finance" / "adapter_model.safetensors"
    with weights.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        verify_adapters(prepared)
