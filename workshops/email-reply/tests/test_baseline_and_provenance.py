import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sft import experiment as sft_experiment
from util.evaluation import build_comparison_identity, validate_comparison_identity
from util.prompts import Hardware, ModelProfile

try:
    from .test_sft_prompt import CharacterTokenizer
except ImportError:
    from test_sft_prompt import CharacterTokenizer


class BaselineAndProvenanceTests(unittest.TestCase):
    def _write_synthetic_dataset(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        rows = [
            {"conversation": "Alpha review schedule?", "reply": "Monday at 10 AM."},
            {"conversation": "Beta contract status?", "reply": "Signed by procurement."},
            {"conversation": "Gamma deployment owner?", "reply": "Dana is leading rollout."},
            {"conversation": "Delta private holdout question?", "reply": "Private holdout answer."},
        ]
        path = directory / "reply-conversations.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return path

    def test_standalone_baseline_and_sft_stage_trees_keep_summaries_text_free_and_render_comparison_png(
        self,
    ):
        mock_torch = Mock()
        mock_torch.cuda.max_memory_allocated.return_value = 300 * 2**20
        mock_torch.cuda.max_memory_reserved.return_value = 500 * 2**20

        def fake_load(prof, hw, *, adapter=None):
            return ("adapted" if adapter else "base"), CharacterTokenizer()

        def fake_fit(model, tokenizer, prof, hw, train, val, output, **kwargs):
            output.mkdir(parents=True, exist_ok=True)
            adapter = output / "adapter"
            adapter.mkdir()
            return adapter, [{"step": 1, "loss": 2.0}, {"step": 1, "eval_loss": 1.7}]

        def fake_eval(model, tokenizer, cases, prof, hw):
            is_sft = model == "adapted"
            return {
                "holdout_rows": len(cases),
                "valid_drafts": len(cases),
                "generation_failures": 0,
                "reference_tokens": 12,
                "mean_reply_words": 4.0 if is_sft else 7.0,
                "reference_token_loss": 1.4 if is_sft else 2.1,
            }, [("SFT private draft." if is_sft else "Baseline private draft.")] * len(cases)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            in_dir = root / "in_data"
            out_root_1 = root / "out_1"
            out_root_2 = root / "out_2"
            self._write_synthetic_dataset(in_dir)

            stdout_1 = io.StringIO()
            with patch("util.paths.restrict_directory"), \
                    patch("sft.experiment.runtime", return_value=(mock_torch, Mock())), \
                    patch("sft.experiment.load_model", side_effect=fake_load), \
                    patch("sft.experiment.fit", side_effect=fake_fit), \
                    patch("sft.experiment.evaluate_model", side_effect=fake_eval), \
                    contextlib.redirect_stdout(stdout_1), \
                    contextlib.redirect_stderr(io.StringIO()):
                sft_experiment.main([
                    "--smoke",
                    "--end-token",
                    "</end>",
                    "--input-dir",
                    str(in_dir),
                    "--output-dir",
                    str(out_root_1),
                ])

            sft_summary_1 = json.loads(stdout_1.getvalue())
            self.assertEqual(sft_summary_1["stage"], "sft")
            self.assertIn("comparison_identity", sft_summary_1)
            self.assertIsNotNone(sft_summary_1["baseline_run"])

            base_dirs = [p for p in (out_root_1 / "baseline").iterdir() if p.is_dir()]
            sft_dirs = [p for p in (out_root_1 / "sft").iterdir() if p.is_dir()]
            self.assertEqual(len(base_dirs), 1)
            self.assertEqual(len(sft_dirs), 1)

            base_summary_path = base_dirs[0] / "summary.json"
            self.assertTrue(base_summary_path.is_file())
            self.assertFalse((base_dirs[0] / "heldout-sample-outputs.txt").exists())
            base_raw = base_summary_path.read_text(encoding="utf-8")
            sft_raw = (sft_dirs[0] / "summary.json").read_text(encoding="utf-8")
            for forbidden in (
                "Baseline private draft.",
                "SFT private draft.",
                "Private holdout answer.",
                "Delta private holdout question?",
            ):
                self.assertNotIn(forbidden, base_raw)
                self.assertNotIn(forbidden, sft_raw)

            comp_png = sft_dirs[0] / "comparison.png"
            self.assertTrue(comp_png.is_file() and comp_png.stat().st_size > 0)
            self.assertEqual(comp_png.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

            # Reuse saved baseline run from out_root_1 inside out_root_2 without altering out_root_1
            before_base_sha = hashlib.sha256(base_summary_path.read_bytes()).hexdigest()
            stdout_2 = io.StringIO()
            with patch("util.paths.restrict_directory"), \
                    patch("sft.experiment.runtime", return_value=(mock_torch, Mock())), \
                    patch("sft.experiment.load_model", side_effect=fake_load), \
                    patch("sft.experiment.fit", side_effect=fake_fit), \
                    patch("sft.experiment.evaluate_model", side_effect=fake_eval), \
                    contextlib.redirect_stdout(stdout_2), \
                    contextlib.redirect_stderr(io.StringIO()):
                sft_experiment.main([
                    "--smoke",
                    "--show-private",
                    "--end-token",
                    "</end>",
                    "--input-dir",
                    str(in_dir),
                    "--output-dir",
                    str(out_root_2),
                    "--baseline-run",
                    str(base_dirs[0]),
                ])

            self.assertEqual(
                hashlib.sha256(base_summary_path.read_bytes()).hexdigest(),
                before_base_sha,
            )
            self.assertFalse((out_root_2 / "baseline").exists())
            sft_dirs_2 = [p for p in (out_root_2 / "sft").iterdir() if p.is_dir()]
            self.assertEqual(len(sft_dirs_2), 1)
            self.assertTrue((sft_dirs_2[0] / "heldout-sample-outputs.txt").is_file())
            self.assertTrue((sft_dirs_2[0] / "comparison.png").is_file())

            # Also verify --baseline-only with --show-private writes baseline samples only in baseline\<run-id>
            out_root_3 = root / "out_3"
            stdout_3 = io.StringIO()
            with patch("util.paths.restrict_directory"), \
                    patch("sft.experiment.runtime", return_value=(mock_torch, Mock())), \
                    patch("sft.experiment.load_model", side_effect=fake_load), \
                    patch("sft.experiment.evaluate_model", side_effect=fake_eval), \
                    contextlib.redirect_stdout(stdout_3), \
                    contextlib.redirect_stderr(io.StringIO()):
                sft_experiment.main([
                    "--smoke",
                    "--baseline-only",
                    "--show-private",
                    "--end-token",
                    "</end>",
                    "--input-dir",
                    str(in_dir),
                    "--output-dir",
                    str(out_root_3),
                ])
            base_only_dirs = [p for p in (out_root_3 / "baseline").iterdir() if p.is_dir()]
            self.assertEqual(len(base_only_dirs), 1)
            base_sample_txt = (base_only_dirs[0] / "heldout-sample-outputs.txt").read_text(encoding="utf-8")
            self.assertIn("Baseline private draft.", base_sample_txt)
            self.assertNotIn("SFT DRAFT", base_sample_txt)

    def test_comparison_identity_rejects_dataset_split_model_budget_and_decoding_mismatches(self):
        profile = ModelProfile(model_id="org/base", revision="a" * 40, end_token="</end>")
        hw = Hardware(max_length=1024, completion_tokens=128)
        expected = build_comparison_identity(
            dataset_sha256="1" * 64,
            split_sha256="2" * 64,
            holdout_lines=[4, 9],
            profile=profile,
            hardware=hw,
        )
        validate_comparison_identity(expected, {"comparison_identity": dict(expected)}, label="baseline")

        mutations = [
            ("dataset SHA-256", {"dataset_sha256": "9" * 64}),
            ("split manifest", {"split_sha256": "8" * 64}),
            ("held-out case list", {"holdout_lines": [4, 10]}),
            ("base model", {"base_model": "org/other"}),
            ("base model revision", {"revision": "b" * 40}),
            ("prompt/completion token budget", {"prompt_budget": {"max_length": 512, "completion_tokens": 128}}),
            ("evaluation decoding settings", {"decoding": {"do_sample": True, "temperature": 0.7}}),
        ]
        for expected_msg, patch_fields in mutations:
            tampered = dict(expected)
            tampered.update(patch_fields)
            with self.assertRaisesRegex(ValueError, expected_msg):
                validate_comparison_identity(
                    expected,
                    {"comparison_identity": tampered},
                    label="baseline",
                )
