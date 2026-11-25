import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sft import experiment as sft_experiment
from util.models import validate_model_targets
from util.paths import (
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_ROOT,
    REPO_ROOT,
    WORKSHOP_ROOT,
    ensure_repo_output_ignored,
    prepare_output_root,
    resolve_input_dir,
)
from util.prompts import ModelProfile


class CustomTemplateTokenizer:
    chat_template = "{{ messages }}"
    pad_token_id = 0
    eos_token_id = 1

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        return "".join(f"<{m['role']}>{m['content']}<|eot_id|>" for m in messages) + (
            "<assistant>" if add_generation_prompt else ""
        )

    def encode(self, text, *, add_special_tokens):
        return [ord(ch) for ch in text.replace("<|eot_id|>", "\x03")]


class PathsAndConfigTests(unittest.TestCase):
    def test_defaults_are_independent_of_caller_working_directory(self):
        with tempfile.TemporaryDirectory() as external_cwd:
            in_dir, dataset_path = resolve_input_dir(None, cwd=Path(external_cwd))
            self.assertEqual(in_dir, DEFAULT_INPUT_DIR)
            self.assertEqual(dataset_path, DEFAULT_INPUT_DIR / "reply-conversations.jsonl")
            with patch("util.paths.restrict_directory"):
                out_root = prepare_output_root(None, cwd=Path(external_cwd))
            self.assertEqual(out_root, DEFAULT_OUTPUT_ROOT)

    def test_caller_relative_overrides_and_invalid_storage_fail_without_fallback(self):
        with tempfile.TemporaryDirectory() as workspace:
            caller = Path(workspace).resolve()
            rel_in = caller / "datasets" / "team_mail"
            rel_in.mkdir(parents=True)
            (rel_in / "reply-conversations.jsonl").write_text(
                json.dumps({"conversation": "Q1?", "reply": "A1."}) + "\n",
                encoding="utf-8",
            )
            resolved_in, _ = resolve_input_dir(r"datasets\team_mail", cwd=caller)
            self.assertEqual(resolved_in, rel_in)

            with patch("util.paths.restrict_directory"):
                resolved_out = prepare_output_root(r"runs\custom_out", cwd=caller, input_dir=resolved_in)
            self.assertEqual(resolved_out, caller / "runs" / "custom_out")
            self.assertTrue(resolved_out.is_dir())

            with self.assertRaisesRegex(ValueError, "Input directory does not exist"):
                resolve_input_dir(r"datasets\missing", cwd=caller)

            empty_dir = caller / "datasets" / "empty"
            empty_dir.mkdir()
            with self.assertRaisesRegex(ValueError, "not found in input directory"):
                resolve_input_dir(empty_dir, cwd=caller)

            with self.assertRaisesRegex(ValueError, "must not overlap an input directory"):
                prepare_output_root(rel_in / "nested", cwd=caller, input_dir=resolved_in)

            file_target = caller / "not_a_dir.txt"
            file_target.write_text("file", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a directory"):
                prepare_output_root(file_target, cwd=caller)

    def test_in_repo_output_requires_gitignore_without_modifying_repo_config(self):
        gitignore_path = REPO_ROOT / ".gitignore"
        before_gitignore = gitignore_path.read_text(encoding="utf-8")
        unignored = WORKSHOP_ROOT / "unignored-test-output-candidate"
        self.assertFalse(unignored.exists())
        with self.assertRaisesRegex(ValueError, "not ignored by Git"):
            prepare_output_root(unignored)
        self.assertFalse(unignored.exists())
        self.assertEqual(gitignore_path.read_text(encoding="utf-8"), before_gitignore)
        ensure_repo_output_ignored(DEFAULT_OUTPUT_ROOT / "nested-check")

    def test_model_target_and_template_validation(self):
        profile = ModelProfile(
            model_id="org/custom-instruct",
            revision="b" * 40,
            target_modules=("q_proj", "v_proj"),
            end_token="<|eot_id|>",
        )
        valid_model = SimpleNamespace(
            named_modules=lambda: [("layers.0.self_attn.q_proj", object()), ("layers.0.self_attn.v_proj", object())]
        )
        validate_model_targets(valid_model, SimpleNamespace(chat_template="{{ messages }}"), profile)

        missing_mod_model = SimpleNamespace(
            named_modules=lambda: [("layers.0.self_attn.q_proj", object())]
        )
        with self.assertRaisesRegex(ValueError, "missing configured LoRA target modules"):
            validate_model_targets(missing_mod_model, SimpleNamespace(chat_template="{{ messages }}"), profile)

        with self.assertRaisesRegex(ValueError, "no chat template"):
            validate_model_targets(valid_model, SimpleNamespace(chat_template=""), profile)

    def test_custom_external_io_and_custom_model_leave_default_output_untouched(self):
        before_default_entries = (
            {p.name for p in (DEFAULT_OUTPUT_ROOT / "sft").iterdir()}
            if (DEFAULT_OUTPUT_ROOT / "sft").exists()
            else set()
        )
        rows = [
            {"conversation": "Project alpha status?", "reply": "On track for Monday."},
            {"conversation": "Budget review room?", "reply": "Conference Room B."},
            {"conversation": "Travel receipt deadline?", "reply": "Submit by Friday noon."},
            {"conversation": "Hardware order update?", "reply": "Arriving next week."},
        ]
        mock_torch = Mock()
        mock_torch.cuda.max_memory_allocated.return_value = 256 * 2**20
        mock_torch.cuda.max_memory_reserved.return_value = 512 * 2**20

        def fake_load(prof, hw, *, adapter=None):
            return ("adapted" if adapter else "base"), CustomTemplateTokenizer()

        def fake_fit(model, tokenizer, prof, hw, train, val, output, **kwargs):
            output.mkdir(parents=True, exist_ok=True)
            adapter = output / "adapter"
            adapter.mkdir()
            return adapter, [{"step": 1, "loss": 1.8}, {"step": 1, "eval_loss": 1.6}]

        def fake_eval(model, tokenizer, cases, prof, hw):
            return {
                "holdout_rows": len(cases),
                "valid_drafts": len(cases),
                "generation_failures": 0,
                "reference_tokens": 8,
                "mean_reply_words": 3.0,
                "reference_token_loss": 1.5,
            }, ["Short draft."] * len(cases)

        with tempfile.TemporaryDirectory() as external_root:
            ext = Path(external_root).resolve()
            custom_in = ext / "my_input"
            custom_out = ext / "my_output"
            custom_in.mkdir()
            (custom_in / "reply-conversations.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8",
            )
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            old_cwd = Path.cwd()
            try:
                os.chdir(ext)
                with patch("util.paths.restrict_directory"), \
                        patch("sft.experiment.runtime", return_value=(mock_torch, Mock())), \
                        patch("sft.experiment.load_model", side_effect=fake_load), \
                        patch("sft.experiment.fit", side_effect=fake_fit), \
                        patch("sft.experiment.evaluate_model", side_effect=fake_eval), \
                        contextlib.redirect_stdout(stdout_buf), \
                        contextlib.redirect_stderr(stderr_buf):
                    sft_experiment.main([
                        "--smoke",
                        "--input-dir",
                        "my_input",
                        "--output-dir",
                        "my_output",
                        "--model-id",
                        "org/custom-instruct",
                        "--target-modules",
                        "q_proj",
                        "v_proj",
                        "--end-token",
                        "<|eot_id|>",
                    ])
            finally:
                os.chdir(old_cwd)

            summary = json.loads(stdout_buf.getvalue())
            self.assertEqual(summary["model"]["model_id"], "org/custom-instruct")
            self.assertIsNone(summary["model"]["revision"])
            self.assertEqual(summary["model"]["target_modules"], ["q_proj", "v_proj"])
            self.assertEqual(summary["model"]["end_token"], "<|eot_id|>")
            self.assertTrue((custom_out / "sft" / "split-42.json").is_file())
            run_dirs = [p for p in (custom_out / "sft").iterdir() if p.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "summary.json").is_file())
            self.assertTrue((run_dirs[0] / "metrics.jsonl").is_file())

        after_default_entries = (
            {p.name for p in (DEFAULT_OUTPUT_ROOT / "sft").iterdir()}
            if (DEFAULT_OUTPUT_ROOT / "sft").exists()
            else set()
        )
        self.assertEqual(before_default_entries, after_default_entries)
