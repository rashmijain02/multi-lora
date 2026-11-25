import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sft import experiment as sft_experiment
from util.data import ReplyPair
from util.evaluation import evaluate, prepare_evaluation, sample_drafts
from util.paths import WORKSHOP_ROOT
from util.prompts import Hardware, ModelProfile

try:
    from .test_sft_prompt import CharacterTokenizer
except ImportError:
    from test_sft_prompt import CharacterTokenizer


class CompareTests(unittest.TestCase):
    def test_paired_inputs_failure_counts_and_reference_denominators(self):
        rows = [ReplyPair(12, "Are you coming?", "Yes"),
                ReplyPair(13, "When?", "A reference too long to fit")]
        cases = prepare_evaluation(rows, CharacterTokenizer(), ModelProfile(end_token="</end>"),
                                   Hardware(max_length=210, completion_tokens=15))
        observed = []

        def generate(ids):
            observed.append(ids)
            if len(observed) == 1:
                raise RuntimeError("Failed generation")
            return ""

        baseline, drafts = evaluate(cases, generate, lambda row: 1.5)
        adapted, new_drafts = evaluate(cases, lambda ids: "Arriving now.", lambda row: 1)
        self.assertEqual(observed, [case.prompt.ids for case in cases])
        self.assertEqual((baseline["generation_failures"], baseline["empty_drafts"]), (1, 1))
        self.assertEqual(adapted["valid_drafts"], 2)
        self.assertEqual(baseline["reference_rows"], 1)
        self.assertEqual(baseline["reference_tokens"], 4)
        self.assertEqual(baseline["reference_token_loss"], 1.5)
        self.assertEqual(baseline["reference_tokens"], adapted["reference_tokens"])
        self.assertEqual(sample_drafts(cases, drafts, new_drafts), [])
        self.assertEqual(sample_drafts(cases, drafts, new_drafts, show_private=True)[0]["reference"], "Yes")

    def test_experiment_script_writes_loss_plot_and_gates_private_samples(self):
        splits = {
            "train": [ReplyPair(1, "Can we meet Tuesday?", "Tuesday at 2pm works.")],
            "validation": [ReplyPair(2, "Need the slide deck?", "Sent this morning.")],
            "holdout": [ReplyPair(3, "Secret project update?", "Confidential target reply.")],
        }
        profile = ModelProfile(end_token="</end>")
        hardware = Hardware(max_length=240, completion_tokens=40)
        torch = Mock()
        torch.cuda.max_memory_allocated.return_value = 512 * 2**20
        torch.cuda.max_memory_reserved.return_value = 768 * 2**20

        def fake_fit(model, tokenizer, prof, hw, train, val, output, **kwargs):
            output.mkdir(parents=True)
            adapter = output / "adapter"
            adapter.mkdir()
            return adapter, [{"step": 1, "loss": 2.4}, {"step": 1, "eval_loss": 2.1}]

        def fake_eval(model, tokenizer, cases, prof, hw):
            tag = "Adapted draft." if model == "adapted" else "Baseline draft."
            return {"valid_drafts": len(cases), "generation_failures": 0, "reference_tokens": 10}, [tag] * len(cases)

        def fake_load(prof, hw, *, adapter=None):
            return ("adapted" if adapter else "base"), CharacterTokenizer()

        with tempfile.TemporaryDirectory() as directory, \
                patch("sft.experiment.private_output", return_value=Path(directory)), \
                patch("sft.experiment.runtime", return_value=(torch, Mock())), \
                patch("sft.experiment.load_model", side_effect=fake_load), \
                patch("sft.experiment.fit", side_effect=fake_fit), \
                patch("sft.experiment.evaluate_model", side_effect=fake_eval):
            default_run = sft_experiment.run(splits, profile, hardware, smoke=True)
            self.assertTrue(default_run.loss_plot.is_file() and default_run.loss_plot.stat().st_size > 0)
            self.assertTrue(
                default_run.diagnostics_plot.is_file() and default_run.diagnostics_plot.stat().st_size > 0
            )
            self.assertTrue(default_run.metrics_file.is_file() and default_run.metrics_file.stat().st_size > 0)
            self.assertIsNone(default_run.samples_file)
            summary_raw = (default_run.run_dir / "summary.json").read_text(encoding="utf-8")
            metrics_raw = default_run.metrics_file.read_text(encoding="utf-8")
            for raw in (summary_raw, metrics_raw):
                self.assertNotIn("Secret project update?", raw)
                self.assertNotIn("Confidential target reply.", raw)

            private_run = sft_experiment.run(splits, profile, hardware, smoke=True, show_private=True)
            self.assertIsNotNone(private_run.samples_file)
            report = private_run.samples_file.read_text(encoding="utf-8")
            for expected in ("Secret project update?", "Baseline draft.", "Adapted draft.", "Confidential target reply."):
                self.assertIn(expected, report)
            private_summary = (private_run.run_dir / "summary.json").read_text(encoding="utf-8")
            self.assertNotIn("Confidential target reply.", private_summary)

    def test_cli_flag_validation_and_direct_execution_from_package_folder(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            sft_experiment.main(["--sample-count", "2"])
        completed = subprocess.run(
            [sys.executable, "experiment.py", "--help"],
            cwd=WORKSHOP_ROOT / "sft",
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--show-private", completed.stdout)
        self.assertIn("--eval-steps", completed.stdout)
