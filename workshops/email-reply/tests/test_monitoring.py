import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from util.monitoring import (
    MetricsLogger,
    build_sft_trainer_callback,
    plot_grpo_diagnostics,
    plot_stage_comparison,
    read_metrics,
    resolve_eval_steps,
    save_figure,
)


class MonitoringTests(unittest.TestCase):
    def test_append_only_telemetry_flushes_incrementally_and_rejects_private_text(self):
        messages: list[str] = []
        with tempfile.TemporaryDirectory() as directory:
            metrics_path = Path(directory).resolve() / "metrics.jsonl"
            logger = MetricsLogger(metrics_path, stage="sft", notify=messages.append)
            logger.record(event="train_step", step=1, total_steps=4, loss=2.8, learning_rate=2e-4)
            with self.assertRaisesRegex(ValueError, "prohibited"):
                logger.record(event="train_step", step=2, conversation="Confidential email body")
            with self.assertRaisesRegex(ValueError, "not allowlisted"):
                logger.record(event="train_step", step=2, custom_note="Leaked draft snippet")
            retained = read_metrics(metrics_path)
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["step"], 1)
            self.assertEqual(len(messages), 1)
            self.assertIn("[sft step 1/4]", messages[0])

    def test_sft_callback_forces_final_eval_and_refreshes_headless_plots(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory).resolve()
            logger = MetricsLogger(run_dir / "metrics.jsonl", stage="sft")
            callback = build_sft_trainer_callback(logger, eval_steps=2, total_steps=3, run_dir=run_dir)
            state = SimpleNamespace(global_step=3, max_steps=3)
            control = SimpleNamespace(should_evaluate=False, should_save=False)
            callback.on_step_begin(None, state, control)
            callback.on_log(None, state, control, logs={"loss": 1.9, "learning_rate": 1e-4, "grad_norm": 0.9})
            callback.on_step_end(None, state, control)
            self.assertTrue(control.should_evaluate)
            self.assertTrue(control.should_save)
            callback.on_log(None, state, control, logs={"eval_loss": 1.7, "eval_runtime": 0.2})
            self.assertTrue((run_dir / "loss.png").is_file() and (run_dir / "loss.png").stat().st_size > 0)
            self.assertTrue(
                (run_dir / "training_metrics.png").is_file()
                and (run_dir / "training_metrics.png").stat().st_size > 0
            )
            records = read_metrics(run_dir / "metrics.jsonl")
            self.assertEqual([r["event"] for r in records], ["train_step", "eval"])
            self.assertEqual(records[-1]["best_step"], 3)

    def test_headless_grpo_and_stage_comparison_plots_render_png_files(self):
        grpo_records = [
            {
                "stage": "grpo",
                "event": "train_step",
                "step": 1,
                "reward_mean": 0.58,
                "reward_std": 0.12,
                "relevance_mean": 2.5,
                "grounding_mean": 2.4,
                "uncertainty_mean": 2.1,
                "kl_mean": 0.02,
                "grad_norm": 1.1,
                "completion_words_mean": 22.0,
                "tied_group_rate": 0.0,
            },
            {
                "stage": "grpo",
                "event": "eval",
                "step": 1,
                "val_reward_mean": 0.62,
                "val_relevance_mean": 2.6,
                "val_grounding_mean": 2.5,
                "val_uncertainty_mean": 2.3,
            },
        ]
        stages = {
            "baseline": {
                "holdout_rows": 4,
                "valid_drafts": 4,
                "mean_reply_words": 31.0,
                "reference_token_loss": 4.2,
                "judge": {"reward_mean": 0.52},
            },
            "sft": {
                "holdout_rows": 4,
                "valid_drafts": 4,
                "mean_reply_words": 19.5,
                "reference_token_loss": 2.8,
                "judge": {"reward_mean": 0.66},
            },
            "grpo": {
                "holdout_rows": 4,
                "valid_drafts": 4,
                "mean_reply_words": 21.0,
                "reference_token_loss": 2.9,
                "judge": {"reward_mean": 0.75},
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            grpo_png = save_figure(plot_grpo_diagnostics(grpo_records), out / "grpo.png")
            comp_png = save_figure(plot_stage_comparison(stages), out / "comparison.png")
            self.assertTrue(grpo_png.read_bytes().startswith(b"\x89PNG"))
            self.assertTrue(comp_png.read_bytes().startswith(b"\x89PNG"))
        self.assertEqual(resolve_eval_steps(None, total_steps=1, smoke=True), 1)
        self.assertEqual(resolve_eval_steps(25, total_steps=4, smoke=False), 4)
