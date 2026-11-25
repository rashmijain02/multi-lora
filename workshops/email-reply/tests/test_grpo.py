"""Unit tests for checkpoint-initialized QLoRA GRPO trainer, telemetry, and CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import grpo.experiment as grpo_exp
import grpo.trainer as grpo_trainer
from grpo.judge import (
    JudgeFailureError,
    JudgeProfile,
    JudgeScore,
    LocalJudge,
    parse_judge_response,
)
from grpo.trainer import (
    POLICY_ADAPTER_NAME,
    REFERENCE_ADAPTER_NAME,
    GRPOConfig,
    compute_group_advantages,
    fit_grpo,
    load_policy_with_sft_reference,
)
from tools import prepare_input
from util.data import load_frozen_split, load_pairs, save_split, split_pairs
from util.evaluation import build_comparison_identity
from util.models import adapter_fingerprint, adapter_identity
from util.monitoring import read_metrics
from util.paths import REPO_ROOT, WORKSHOP_ROOT
from util.prompts import Hardware, ModelProfile, prepare_prompt

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ALT_SHA = "1111111111111111111111111111111111111111"


class ToyTokenizer:
    pad_token_id = 0
    eos_token_id = 2
    chat_template = "toy-chat-template"

    def __init__(self) -> None:
        self._id_to_word: dict[int, str] = {0: "", 1: "<bos>", 2: "<|im_end|>"}
        self._word_to_id: dict[str, int] = {"<bos>": 1, "<|im_end|>": 2}

    def _intern(self, word: str) -> int:
        if word not in self._word_to_id:
            idx = len(self._id_to_word) + 3
            self._word_to_id[word] = idx
            self._id_to_word[idx] = word
        return self._word_to_id[word]

    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool = True,
        add_generation_prompt: bool = False,
    ):
        words: list[str] = ["<bos>"]
        for msg in messages:
            words.append(f"[{msg['role']}]")
            words.extend(msg["content"].split())
            words.append("<|im_end|>")
        if add_generation_prompt:
            words.append("[assistant]")
        if not tokenize:
            return " ".join(words)
        return [self._intern(w) for w in words]

    def convert_tokens_to_ids(self, token: str) -> int:
        return self._intern(token)

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return [self._intern(w) for w in text.split()] if text.strip() else []

    def decode(self, ids, skip_special_tokens: bool = True) -> str:
        raw_ids = ids.tolist() if hasattr(ids, "tolist") else list(ids)
        words = []
        for idx in raw_ids:
            word = self._id_to_word.get(int(idx), f"tok{int(idx)}")
            if skip_special_tokens and word in ("", "<bos>", "<|im_end|>", "[assistant]"):
                continue
            words.append(word)
        return " ".join(words)


def _write_fake_sft_adapter(adapter_dir: Path, profile: ModelProfile, *, init_value: float = 0.75) -> Path:
    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "experiment-base.json").write_text(
        json.dumps(adapter_identity(profile), indent=2),
        encoding="utf-8",
    )
    (adapter_dir / "adapter_config.json").write_text(
        json.dumps(
            {
                "peft_type": "LORA",
                "r": 4,
                "lora_alpha": 8,
                "target_modules": list(profile.target_modules),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (adapter_dir / "adapter_model.safetensors").write_bytes(
        json.dumps({"init_value": init_value}).encode("utf-8")
    )
    return adapter_dir


def _build_dual_adapter_toy_model(
    tokenizer: ToyTokenizer,
    sft_adapter: Path,
    *,
    vocab_size: int = 256,
    candidate_schedule: list[str] | None = None,
):
    import torch
    from torch import nn

    init_payload = json.loads((sft_adapter / "adapter_model.safetensors").read_text(encoding="utf-8"))
    init_val = float(init_payload["init_value"])

    class DualAdapterToyModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.device = "cpu"
            self.active_adapter = POLICY_ADAPTER_NAME
            self.peft_config = {POLICY_ADAPTER_NAME: {"inference_mode": False}}
            self.adapter_history: list[str] = []
            self.base_proj = nn.Parameter(torch.full((vocab_size,), 0.1), requires_grad=False)
            self.policy_lora = nn.Parameter(
                torch.linspace(init_val, init_val + 0.5, steps=vocab_size),
                requires_grad=True,
            )
            self.ref_lora: nn.Parameter | None = None
            self._schedule = list(
                candidate_schedule
                or [
                    "Grounded concise reply confirming Tuesday budget deck.",
                    "Invented $9M budget and 5pm flight.",
                    "Grounded summary asking only missing approver name.",
                    "Brief grounded confirmation of attachment receipt.",
                ]
            )
            self._gen_idx = 0

        def named_modules(self, *args, **kwargs):
            target_names = ModelProfile().target_modules
            yield "", self
            for t_name in target_names:
                yield f"layers.0.{t_name}", self

        def named_parameters(self, prefix: str = "", recurse: bool = True):
            yield "layers.0.q_proj.base.weight", self.base_proj
            yield f"layers.0.q_proj.lora_A.{POLICY_ADAPTER_NAME}.weight", self.policy_lora
            if self.ref_lora is not None:
                yield f"layers.0.q_proj.lora_A.{REFERENCE_ADAPTER_NAME}.weight", self.ref_lora

        def load_adapter(self, model_id: str, adapter_name: str, is_trainable: bool = False, **kwargs) -> None:
            payload = json.loads(
                (Path(model_id) / "adapter_model.safetensors").read_text(encoding="utf-8")
            )
            val = float(payload["init_value"])
            self.ref_lora = nn.Parameter(
                torch.linspace(val, val + 0.5, steps=vocab_size),
                requires_grad=is_trainable,
            )
            self.peft_config[adapter_name] = {"inference_mode": not is_trainable}
            # Mirror PEFT behavior where load_adapter switches active adapter / freezes non-active.
            self.active_adapter = adapter_name
            self.policy_lora.requires_grad_(False)

        def set_adapter(self, adapter_name: str) -> None:
            if adapter_name not in self.peft_config:
                raise KeyError(f"Unknown adapter: {adapter_name}")
            self.active_adapter = adapter_name
            self.adapter_history.append(adapter_name)

        def disable_adapter(self):
            raise AssertionError("disable_adapter() must NEVER be called for GRPO SFT reference KL!")

        def forward(self, input_ids, attention_mask=None, labels=None, use_cache=False):
            batch, seq_len = input_ids.shape
            active_vec = (
                self.policy_lora
                if self.active_adapter == POLICY_ADAPTER_NAME or self.ref_lora is None
                else self.ref_lora
            )
            pos_scale = torch.arange(1, seq_len + 1, dtype=torch.float32).view(1, seq_len, 1) * 0.05
            logits = (self.base_proj + active_vec).view(1, 1, vocab_size).expand(batch, seq_len, vocab_size)
            logits = logits + pos_scale
            loss = None
            if labels is not None:
                import torch.nn.functional as F

                shift_logits = logits[:, :-1, :].contiguous()
                shift_labels = labels[:, 1:].contiguous()
                loss = F.cross_entropy(
                    shift_logits.view(-1, vocab_size),
                    shift_labels.view(-1),
                    ignore_index=-100,
                )
            return types.SimpleNamespace(logits=logits, loss=loss)

        def generate(self, input_ids, attention_mask=None, max_new_tokens=32, do_sample=False, **kwargs):
            text = self._schedule[self._gen_idx % len(self._schedule)]
            self._gen_idx += 1
            if text == "__RUNTIME_ERROR__":
                raise RuntimeError("Synthetic non-OOM generation glitch")
            comp = tokenizer.encode(text)
            if comp:
                comp = comp[: max(1, max_new_tokens - 1)] + [tokenizer.eos_token_id]
            out_ids = input_ids[0].tolist() + comp
            return torch.tensor([out_ids], dtype=torch.long)

        def save_pretrained(self, save_directory, selected_adapters=None, **kwargs):
            target = Path(save_directory)
            target.mkdir(parents=True, exist_ok=True)
            assert selected_adapters in (None, [POLICY_ADAPTER_NAME])
            (target / "adapter_config.json").write_text(
                json.dumps({"peft_type": "LORA", "r": 4}),
                encoding="utf-8",
            )
            (target / "adapter_model.safetensors").write_text(
                json.dumps({"init_value": float(self.policy_lora[0].detach().item())}),
                encoding="utf-8",
            )

    return DualAdapterToyModel()


class ProgrammableJudge(LocalJudge):
    """Deterministic in-memory LocalJudge double using real JudgeScore validation."""

    def __init__(self, scorer, profile: JudgeProfile | None = None) -> None:
        self.profile = profile or JudgeProfile()
        self.tokenizer = ToyTokenizer()
        self._scorer = scorer
        self.calls: list[tuple[str, str]] = []

    def score_one(self, conversation: str, candidate_reply: str) -> JudgeScore:
        self.calls.append((conversation, candidate_reply))
        rel, grd, unc = self._scorer(conversation, candidate_reply, len(self.calls))
        return parse_judge_response(
            json.dumps({"relevance": rel, "grounding": grd, "uncertainty": unc})
        )

    score_draft = score_one


class GRPOTests(unittest.TestCase):
    def test_config_and_group_advantage_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "group_size"):
            GRPOConfig(group_size=1)
        with self.assertRaisesRegex(ValueError, "temperature"):
            GRPOConfig(temperature=0.0)
        with self.assertRaisesRegex(ValueError, "beta"):
            GRPOConfig(beta=0.0)

        tied_adv, tied_std, is_tied = compute_group_advantages([0.5, 0.5, 0.5, 0.5])
        self.assertTrue(is_tied)
        self.assertEqual(tied_std, 0.0)
        self.assertEqual(tied_adv, [0.0, 0.0, 0.0, 0.0])

        varied_adv, varied_std, is_tied_v = compute_group_advantages([0.25, 0.75])
        self.assertFalse(is_tied_v)
        self.assertAlmostEqual(varied_std, 0.25)
        self.assertAlmostEqual(varied_adv[0], -1.0)
        self.assertAlmostEqual(varied_adv[1], 1.0)

    def test_checkpoint_init_preserves_sft_weights_rejects_mismatch_and_keeps_ref_immutable(self) -> None:
        import torch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = ModelProfile()
            hw = Hardware(max_length=256, completion_tokens=32)
            sft_dir = _write_fake_sft_adapter(root / "sft_adapter", profile, init_value=0.75)
            source_fp_before = adapter_fingerprint(sft_dir)

            wrong_profile = ModelProfile(revision=ALT_SHA)
            with mock.patch.object(grpo_trainer, "load_model") as mocked_load:
                with self.assertRaisesRegex(ValueError, "different base model, revision, or target set"):
                    load_policy_with_sft_reference(wrong_profile, hw, sft_dir)
                mocked_load.assert_not_called()

            tokenizer = ToyTokenizer()
            toy_model = _build_dual_adapter_toy_model(tokenizer, sft_dir)
            with mock.patch.object(
                grpo_trainer,
                "load_model",
                return_value=(toy_model, tokenizer),
            ):
                loaded_model, _ = load_policy_with_sft_reference(profile, hw, sft_dir)

            self.assertTrue(loaded_model.policy_lora.requires_grad)
            self.assertIsNotNone(loaded_model.ref_lora)
            self.assertFalse(loaded_model.ref_lora.requires_grad)
            # SFT learned weights are preserved (0.75..1.25), not reset to zeros!
            self.assertAlmostEqual(float(loaded_model.policy_lora[0].item()), 0.75, places=5)
            self.assertTrue(torch.allclose(loaded_model.policy_lora.detach(), loaded_model.ref_lora.detach()))

            train_prompts = [
                prepare_prompt(tokenizer, hw, "SECRET_TRAIN_THREAD_ALPHA: Please confirm Tuesday deck."),
                prepare_prompt(tokenizer, hw, "SECRET_TRAIN_THREAD_BETA: Did legal sign the NDA?"),
            ]
            val_prompts = [
                prepare_prompt(tokenizer, hw, "SECRET_VAL_THREAD_GAMMA: Share Q3 summary status."),
            ]
            holdout_marker = "SECRET_HOLDOUT_NEVER_TOUCHED_OMEGA"

            def score_fn(conv: str, draft: str, _call_no: int) -> tuple[int, int, int]:
                self.assertNotIn(holdout_marker, conv)
                if "Invented" in draft:
                    return (2, 0, 0)
                return (4, 4, 3)

            judge = ProgrammableJudge(score_fn)
            out_dir = root / "grpo_run"
            with mock.patch.object(grpo_trainer, "runtime", return_value=(torch, object())):
                fit_res = fit_grpo(
                    loaded_model,
                    tokenizer,
                    judge,
                    profile,
                    hw,
                    GRPOConfig(group_size=3, learning_rate=5e-2, max_steps=2, eval_steps=1),
                    train_prompts,
                    val_prompts,
                    out_dir,
                    sft_adapter=sft_dir,
                    dataset_sha256="a" * 64,
                    split_sha256="b" * 64,
                )

            # Policy moved, frozen reference stayed bit-identical, disable_adapter was NEVER called,
            # and "sft_ref" was explicitly routed via set_adapter.
            self.assertIn(REFERENCE_ADAPTER_NAME, loaded_model.adapter_history)
            self.assertAlmostEqual(float(loaded_model.ref_lora[0].item()), 0.75, places=6)
            self.assertNotAlmostEqual(float(loaded_model.policy_lora[0].item()), 0.75, places=5)
            self.assertEqual(adapter_fingerprint(sft_dir), source_fp_before)
            self.assertTrue((fit_res.adapter_dir / "experiment-base.json").is_file())
            self.assertTrue(fit_res.lineage_file.is_file())
            self.assertGreaterEqual(fit_res.lineage["optimizer_updates"], 1)

    def test_tied_groups_invalid_generations_validation_selection_and_interrupted_jsonl(self) -> None:
        import torch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = ModelProfile()
            hw = Hardware(max_length=256, completion_tokens=32)
            sft_dir = _write_fake_sft_adapter(root / "sft_adapter", profile, init_value=0.5)
            tokenizer = ToyTokenizer()

            # Step 1 (3 rollouts): all tied rewards -> zero advantage, tied_groups=1, no update
            # Step 2 (3 rollouts): 1 invalid empty + 2 varied valid -> real update!
            # Val @ step 2: high score (4,4,4) -> best_step = 2
            # Step 3 (3 rollouts): 1 runtime glitch + 2 varied valid -> second update!
            # Val @ step 3: lower score (2,2,2) -> checkpoint selection restores step 2 weights!
            schedule = [
                # Step 1 rollouts (3):
                "Tied draft one.",
                "Tied draft two.",
                "Tied draft three.",
                # Step 2 rollouts (3):
                "   ",
                "Strong grounded draft.",
                "Weak ungrounded draft.",
                # Val @ step 2 (1):
                "Best validation draft.",
                # Step 3 rollouts (3):
                "__RUNTIME_ERROR__",
                "Another strong draft.",
                "Another weak draft.",
                # Val @ step 3 (1):
                "Worse validation draft.",
            ]
            toy_model = _build_dual_adapter_toy_model(tokenizer, sft_dir, candidate_schedule=schedule)
            toy_model.load_adapter(str(sft_dir), adapter_name=REFERENCE_ADAPTER_NAME, is_trainable=False)

            def score_fn(_conv: str, draft: str, _idx: int) -> tuple[int, int, int]:
                if draft.startswith("Tied"):
                    return (3, 3, 3)
                if "Best validation" in draft:
                    return (4, 4, 4)
                if "Worse validation" in draft:
                    return (1, 2, 1)
                if "Strong" in draft or "strong" in draft:
                    return (4, 4, 3)
                return (1, 0, 1)

            train_prompts = [prepare_prompt(tokenizer, hw, "PRIVATE_CONV_SECRET_123: Status update?")]
            val_prompts = [prepare_prompt(tokenizer, hw, "PRIVATE_VAL_SECRET_456: Confirm timeline.")]
            out_dir = root / "grpo_select"

            with mock.patch.object(grpo_trainer, "runtime", return_value=(torch, object())):
                res = fit_grpo(
                    toy_model,
                    tokenizer,
                    ProgrammableJudge(score_fn),
                    profile,
                    hw,
                    GRPOConfig(group_size=3, learning_rate=0.08, max_steps=3, eval_steps=2),
                    train_prompts,
                    val_prompts,
                    out_dir,
                    sft_adapter=sft_dir,
                    dataset_sha256="c" * 64,
                    split_sha256="d" * 64,
                )

            self.assertEqual(res.lineage["best_validation_step"], 2)
            self.assertEqual(res.lineage["tied_groups"], 1)
            self.assertEqual(res.lineage["invalid_completions"], 2)
            self.assertEqual(res.lineage["optimizer_updates"], 2)
            self.assertTrue(res.diagnostics_plot.read_bytes().startswith(PNG_MAGIC))

            raw_metrics_text = res.metrics_file.read_text(encoding="utf-8")
            self.assertNotIn("PRIVATE_CONV_SECRET_123", raw_metrics_text)
            self.assertNotIn("PRIVATE_VAL_SECRET_456", raw_metrics_text)
            records = read_metrics(res.metrics_file)
            train_steps = [r for r in records if r["event"] == "train_step"]
            eval_steps = [r for r in records if r["event"] == "eval"]
            self.assertEqual(len(train_steps), 3)
            self.assertEqual(train_steps[0]["tied_groups"], 1)
            self.assertFalse(train_steps[0]["step_updated"])
            self.assertTrue(train_steps[1]["step_updated"])
            self.assertEqual([e["step"] for e in eval_steps], [2, 3])
            self.assertEqual(eval_steps[-1]["best_step"], 2)

            # Now verify interrupted run retains step-1 JSONL without private text,
            # and all-tied run refuses to claim a successful update!
            fail_dir = root / "grpo_interrupted"
            interrupted_model = _build_dual_adapter_toy_model(tokenizer, sft_dir)
            interrupted_model.load_adapter(
                str(sft_dir), adapter_name=REFERENCE_ADAPTER_NAME, is_trainable=False
            )

            def explode_on_step_two(_conv: str, draft: str, call_no: int) -> tuple[int, int, int]:
                if call_no > 3:
                    raise JudgeFailureError("Judge crashed mid-run on step 2")
                return (4, 4, 4) if "Grounded" in draft else (1, 1, 1)

            with (
                mock.patch.object(grpo_trainer, "runtime", return_value=(torch, object())),
                self.assertRaisesRegex(JudgeFailureError, "crashed mid-run"),
            ):
                fit_grpo(
                    interrupted_model,
                    tokenizer,
                    ProgrammableJudge(explode_on_step_two),
                    profile,
                    hw,
                    GRPOConfig(group_size=2, learning_rate=0.05, max_steps=3, eval_steps=2),
                    train_prompts,
                    val_prompts,
                    fail_dir,
                    sft_adapter=sft_dir,
                    dataset_sha256="c" * 64,
                    split_sha256="d" * 64,
                )
            retained = read_metrics(fail_dir / "metrics.jsonl")
            self.assertEqual(len(retained), 1)
            self.assertEqual(retained[0]["step"], 1)
            self.assertNotIn("PRIVATE_CONV_SECRET_123", (fail_dir / "metrics.jsonl").read_text(encoding="utf-8"))

            no_update_dir = root / "grpo_no_update"
            tied_model = _build_dual_adapter_toy_model(tokenizer, sft_dir)
            tied_model.load_adapter(str(sft_dir), adapter_name=REFERENCE_ADAPTER_NAME, is_trainable=False)
            with (
                mock.patch.object(grpo_trainer, "runtime", return_value=(torch, object())),
                self.assertRaisesRegex(RuntimeError, "without demonstrating a trainable policy update"),
            ):
                fit_grpo(
                    tied_model,
                    tokenizer,
                    ProgrammableJudge(lambda _c, _d, _n: (2, 2, 2)),
                    profile,
                    hw,
                    GRPOConfig(group_size=2, max_steps=2, eval_steps=2),
                    train_prompts,
                    val_prompts,
                    no_update_dir,
                    sft_adapter=sft_dir,
                    dataset_sha256="c" * 64,
                    split_sha256="d" * 64,
                )

    def test_cli_validation_and_end_to_end_converted_input_three_stage_comparison(self) -> None:
        import torch

        # 1. Verify CLI help works from repo root, workshop root, and grpo package directory.
        for cwd in (REPO_ROOT, WORKSHOP_ROOT, WORKSHOP_ROOT / "grpo"):
            proc = subprocess.run(
                [sys.executable, str(WORKSHOP_ROOT / "grpo" / "experiment.py"), "--help"],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("--judge-model-id", proc.stdout)
            self.assertIn("--sft-adapter", proc.stdout)
            self.assertIn("--eval-steps", proc.stdout)

        # Missing SFT adapter or hosted judge URL is rejected cleanly via SystemExit.
        with self.assertRaisesRegex(SystemExit, "Pass --sft-run <dir> or --sft-adapter <dir>"):
            grpo_exp.main([])
        with self.assertRaisesRegex(SystemExit, "Hosted or remote API judge endpoints are not permitted"):
            grpo_exp.main(
                [
                    "--sft-adapter",
                    "some_dir",
                    "--judge-model-id",
                    "https://api.example.com/judge",
                ]
            )

        # 2. End-to-end mocked pipeline starting from synthetic thread conversion!
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_json = root / "threads.json"
            threads = []
            for idx in range(12):
                threads.append(
                    {
                        "thread_id": f"thread-{idx}",
                        "messages": [
                            {
                                "message_id": f"m-{idx}-1",
                                "sender": f"sender{idx}@example.com",
                                "recipients": ["owner@example.com"],
                                "subject": f"Topic {idx}",
                                "timestamp": f"2001-06-{10 + idx:02d}T09:00:00Z",
                                "body": f"CONFIDENTIAL_INPUT_{idx}: Can you confirm item {idx}?",
                            },
                            {
                                "message_id": f"m-{idx}-2",
                                "in_reply_to": f"m-{idx}-1",
                                "sender": "owner@example.com",
                                "recipients": [f"sender{idx}@example.com"],
                                "subject": f"Re: Topic {idx}",
                                "timestamp": f"2001-06-{10 + idx:02d}T10:00:00Z",
                                "body": f"CONFIDENTIAL_REPLY_{idx}: Confirmed item {idx} for Tuesday.",
                            },
                        ],
                    }
                )
            raw_json.write_text(json.dumps(threads), encoding="utf-8")
            custom_in = root / "converted_input"
            rc = prepare_input.main(
                [
                    "--format",
                    "json",
                    "--source",
                    str(raw_json),
                    "--output-dir",
                    str(custom_in),
                    "--target-sender",
                    "owner@example.com",
                ]
            )
            self.assertEqual(rc, 0)

            pairs, excluded, digest = load_pairs(custom_in / "reply-conversations.jsonl")
            splits = split_pairs(pairs, seed=42)
            custom_out = root / "custom_output"
            sft_stage_root = custom_out / "sft"
            sft_stage_root.mkdir(parents=True, exist_ok=True)
            manifest_path = sft_stage_root / "split-42.json"
            save_split(manifest_path, splits, digest, 42)
            data_report = {
                "source_sha256": digest,
                "accepted": len(pairs),
                "splits": {name: len(split) for name, split in splits.items()},
                "holdout_fraction": round(len(splits["holdout"]) / len(pairs), 4),
                "excluded": excluded,
            }

            # Verify frozen split rejects tampered dataset SHA-256.
            tampered_manifest = root / "tampered-split.json"
            tampered_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            tampered_data["source_sha256"] = "f" * 64
            tampered_manifest.write_text(json.dumps(tampered_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
                load_frozen_split(tampered_manifest, pairs, digest)

            loaded_splits, _loaded_manifest, split_sha = load_frozen_split(
                manifest_path, pairs, digest
            )
            self.assertTrue(
                {p.line for p in loaded_splits["train"]}.isdisjoint(
                    p.line for p in loaded_splits["holdout"]
                )
            )

            profile = ModelProfile()
            hw = Hardware(max_length=256, completion_tokens=32)
            sft_run_dir = sft_stage_root / "smoke-sft0001"
            sft_adapter = _write_fake_sft_adapter(sft_run_dir / "adapter", profile, init_value=0.6)

            tokenizer = ToyTokenizer()
            heldout_lines = [p.line for p in loaded_splits["holdout"][:2]]
            comp_id = build_comparison_identity(
                dataset_sha256=data_report["source_sha256"],
                split_sha256=split_sha,
                holdout_lines=heldout_lines,
                profile=profile,
                hardware=Hardware(max_length=256, completion_tokens=32, accumulation=1),
            )
            (sft_run_dir / "summary.json").write_text(
                json.dumps(
                    {
                        "stage": "sft",
                        "comparison_identity": comp_id,
                        "fine_tuned": {
                            "holdout_rows": len(heldout_lines),
                            "truncated_inputs": 0,
                            "valid_drafts": len(heldout_lines),
                            "generation_failures": 0,
                            "empty_drafts": 0,
                            "mean_reply_words": 6.0,
                            "reference_rows": len(heldout_lines),
                            "reference_tokens": 14,
                            "reference_token_loss": 2.1,
                        },
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            def fake_load_model(prof, hardware, *, adapter=None, is_trainable=False, adapter_name="default"):
                m = _build_dual_adapter_toy_model(tokenizer, sft_adapter if adapter is None else Path(adapter) if (Path(adapter) / "adapter_model.safetensors").exists() else sft_adapter)
                return m, tokenizer

            def fake_load_policy_and_ref(prof, hardware, adapter_path):
                m = _build_dual_adapter_toy_model(tokenizer, adapter_path)
                m.load_adapter(str(adapter_path), adapter_name=REFERENCE_ADAPTER_NAME, is_trainable=False)
                return m, tokenizer

            judge = ProgrammableJudge(
                lambda _c, draft, _n: (4, 4, 4) if "Grounded" in draft else (2, 1, 2)
            )

            with (
                mock.patch.object(grpo_exp, "runtime", return_value=(torch, object())),
                mock.patch.object(grpo_trainer, "runtime", return_value=(torch, object())),
                mock.patch.object(grpo_exp, "load_model", side_effect=fake_load_model),
                mock.patch.object(
                    grpo_exp,
                    "load_policy_with_sft_reference",
                    side_effect=fake_load_policy_and_ref,
                ),
            ):
                result = grpo_exp.run(
                    loaded_splits,
                    profile,
                    hw,
                    JudgeProfile(),
                    GRPOConfig(group_size=3, learning_rate=0.05, max_steps=2, eval_steps=1),
                    sft_adapter=sft_adapter,
                    dataset_sha256=data_report["source_sha256"],
                    split_sha256=split_sha,
                    sft_run=sft_run_dir,
                    smoke=True,
                    show_private=False,
                    input_dir=custom_in,
                    output_root=custom_out,
                    split_manifest=manifest_path,
                    dataset=data_report,
                    judge_instance=judge,
                )

                # Incompatible baseline run is rejected when reused.
                bad_base_dir = custom_out / "baseline" / "bad-base"
                bad_base_dir.mkdir(parents=True, exist_ok=True)
                (bad_base_dir / "summary.json").write_text(
                    json.dumps(
                        {
                            "stage": "baseline",
                            "comparison_identity": {**comp_id, "revision": ALT_SHA},
                            "evaluation": result.baseline,
                        }
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ValueError, "base model revision mismatch"):
                    grpo_exp.run(
                        loaded_splits,
                        profile,
                        hw,
                        JudgeProfile(),
                        GRPOConfig(group_size=2, max_steps=1),
                        sft_adapter=sft_adapter,
                        dataset_sha256=data_report["source_sha256"],
                        split_sha256=split_sha,
                        baseline_run=bad_base_dir,
                        smoke=True,
                        output_root=custom_out,
                        judge_instance=judge,
                    )

            self.assertTrue(result.baseline_run_dir.is_dir())
            self.assertEqual(result.baseline_run_dir.parent.name, "baseline")
            self.assertEqual(result.run_dir.parent.name, "grpo")
            self.assertIsNone(result.samples_file)
            self.assertTrue(result.diagnostics_plot.read_bytes().startswith(PNG_MAGIC))
            self.assertTrue(result.comparison_plot.read_bytes().startswith(PNG_MAGIC))
            self.assertTrue((result.grpo_adapter_dir / "adapter_model.safetensors").is_file())
            self.assertTrue((result.grpo_adapter_dir / "grpo-lineage.json").is_file())

            summary_raw = (result.run_dir / "summary.json").read_text(encoding="utf-8")
            self.assertNotIn("CONFIDENTIAL_INPUT_", summary_raw)
            self.assertNotIn("CONFIDENTIAL_REPLY_", summary_raw)
            summary_obj = json.loads(summary_raw)
            self.assertEqual(summary_obj["stage"], "grpo")
            self.assertIn("judge", summary_obj["baseline"])
            self.assertIn("judge", summary_obj["sft"])
            self.assertIn("judge", summary_obj["grpo"])
            # Converted input directory has zero training artifacts written into it!
            self.assertEqual(
                sorted(p.name for p in custom_in.iterdir()),
                ["reply-conversations.jsonl"],
            )

            # Verify CLI main() requires neither --revision nor --judge-model-id/--judge-revision,
            # and inherits a saved SFT adapter's explicit revision when --revision is omitted.
            pinned_profile = ModelProfile(revision=ALT_SHA)
            pinned_sft_dir = custom_out / "sft" / "sft-pinned"
            pinned_adapter = pinned_sft_dir / "adapter"
            pinned_adapter.mkdir(parents=True, exist_ok=True)
            (pinned_sft_dir / "summary.json").write_text(
                json.dumps({"stage": "sft", "split_manifest": str(manifest_path)}),
                encoding="utf-8",
            )
            (pinned_adapter / "adapter_config.json").write_text("{}", encoding="utf-8")
            (pinned_adapter / "adapter_model.safetensors").write_bytes(b"pinned-sft")
            (pinned_adapter / "experiment-base.json").write_text(
                json.dumps(adapter_identity(pinned_profile)),
                encoding="utf-8",
            )
            captured_call: dict[str, object] = {}

            def fake_run_cli(splits_arg, prof_arg, hw_arg, judge_prof_arg, cfg_arg, **kwargs):
                captured_call["profile"] = prof_arg
                captured_call["judge_profile"] = judge_prof_arg
                return result

            with mock.patch("grpo.experiment.run", side_effect=fake_run_cli), \
                    mock.patch("sys.stdout", new=types.SimpleNamespace(write=lambda *_: None, flush=lambda: None)):
                grpo_exp.main(
                    [
                        "--sft-run",
                        str(pinned_sft_dir),
                        "--input-dir",
                        str(custom_in),
                        "--output-dir",
                        str(custom_out),
                        "--smoke",
                    ]
                )
            self.assertEqual(captured_call["profile"].revision, ALT_SHA)
            self.assertEqual(captured_call["judge_profile"].model_id, JudgeProfile().model_id)
            self.assertIsNone(captured_call["judge_profile"].revision)


if __name__ == "__main__":
    unittest.main()
