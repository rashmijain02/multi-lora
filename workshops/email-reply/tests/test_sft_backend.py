import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sft.trainer import adapter_identity, check_adapter, fit, load_model
from util.monitoring import read_metrics
from util.prompts import Hardware, ModelProfile


class BackendTests(unittest.TestCase):
    def test_base_load_is_pinned_and_never_uses_an_adapter(self):
        profile = ModelProfile()
        torch = Mock()
        backend = Mock()
        backend.from_pretrained.return_value = ("base", "tokenizer")
        with patch("util.models.runtime", return_value=(torch, backend)):
            self.assertEqual(load_model(profile, Hardware()), ("base", "tokenizer"))
        backend.from_pretrained.assert_called_once()
        self.assertEqual(backend.from_pretrained.call_args.kwargs["model_name"], profile.model_id)
        self.assertEqual(backend.from_pretrained.call_args.kwargs["revision"], profile.revision)
        self.assertTrue(backend.from_pretrained.call_args.kwargs["use_exact_model_name"])

    def test_adapter_rejects_another_revision_before_loading_any_model(self):
        profile = ModelProfile()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "experiment-base.json").write_text(
                json.dumps(adapter_identity(profile)), encoding="utf-8",
            )
            check_adapter(path, profile)
            with patch("util.models.runtime") as runtime:
                with self.assertRaisesRegex(ValueError, "different base model"):
                    load_model(replace(profile, revision="a" * 40), Hardware(), adapter=path)
                runtime.assert_not_called()

    def test_sft_uses_periodic_validation_for_selection_writes_telemetry_and_reloads_peft(self):
        profile = ModelProfile()
        tokenizer = SimpleNamespace(pad_token_id=0, eos_token_id=1)
        train = [{"input_ids": [2, 1], "labels": [-100, 1]} for _ in range(6)]
        validation = [{"input_ids": [3, 1], "labels": [-100, 1]}]
        trainer = Mock()
        trainer.state = SimpleNamespace(
            best_model_checkpoint="checkpoint-2",
            log_history=[
                {"step": 1, "epoch": 0.5, "loss": 3.2, "learning_rate": 2e-4, "grad_norm": 1.4},
                {"step": 1, "epoch": 0.5, "eval_loss": 2.9},
                {"step": 2, "epoch": 1.0, "loss": 2.4, "learning_rate": 1e-4, "grad_norm": 1.1},
                {"step": 2, "epoch": 1.0, "eval_loss": 2.1},
            ],
        )
        trainer.save_model.side_effect = lambda path: Path(path).mkdir()
        trainer_factory, args_factory = Mock(return_value=trainer), Mock()
        peft = Mock()
        backend = Mock()
        backend.from_pretrained.return_value = ("base", tokenizer)
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = False
        with tempfile.TemporaryDirectory() as directory, \
                patch("sft.trainer.runtime", return_value=(mock_torch, backend)), \
                patch("util.models.runtime", return_value=(mock_torch, backend)), \
                patch.dict("sys.modules", {
                    "transformers": SimpleNamespace(Trainer=trainer_factory, TrainingArguments=args_factory),
                    "peft": SimpleNamespace(PeftModel=peft),
                }):
            output = Path(directory) / "run"
            adapter, _ = fit(
                "base", tokenizer, profile, Hardware(accumulation=3), train, validation, output, eval_steps=1
            )
            self.assertTrue(args_factory.call_args.kwargs["load_best_model_at_end"])
            self.assertEqual(args_factory.call_args.kwargs["eval_strategy"], "steps")
            self.assertEqual(args_factory.call_args.kwargs["eval_steps"], 1)
            self.assertEqual(args_factory.call_args.kwargs["save_strategy"], "steps")
            self.assertEqual(args_factory.call_args.kwargs["save_steps"], 1)
            self.assertEqual(args_factory.call_args.kwargs["metric_for_best_model"], "eval_loss")
            self.assertIs(trainer_factory.call_args.kwargs["train_dataset"], train)
            self.assertIs(trainer_factory.call_args.kwargs["eval_dataset"], validation)
            records = read_metrics(output / "metrics.jsonl")
            self.assertEqual([r["event"] for r in records], ["train_step", "eval", "train_step", "eval"])
            self.assertEqual(records[-1]["best_step"], 2)
            self.assertTrue((output / "loss.png").is_file() and (output / "loss.png").stat().st_size > 0)
            self.assertTrue(
                (output / "training_metrics.png").is_file()
                and (output / "training_metrics.png").stat().st_size > 0
            )
            load_model(profile, Hardware(), adapter=adapter)
            peft.from_pretrained.assert_called_once_with("base", adapter, is_trainable=False)
