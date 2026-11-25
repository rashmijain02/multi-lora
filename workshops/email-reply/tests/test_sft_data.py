import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from util import data as sft_data
from util import paths as util_paths
from util.data import (
    ReplyPair,
    conversation_groups,
    load_frozen_split,
    load_pairs,
    save_split,
    split_pairs,
)


class ReplyDatasetTests(unittest.TestCase):
    def test_output_tree_is_created_and_restricted_without_input_data(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "output" / "sft"
            with patch.object(sft_data, "OUTPUT", output), \
                    patch.object(util_paths, "restrict_directory") as restrict:
                self.assertEqual(sft_data.private_output(), output)
                self.assertTrue(output.is_dir())
                self.assertEqual(restrict.call_args_list, [call(output.parent), call(output)])
                restrict.reset_mock()
                self.assertEqual(sft_data.private_output(), output)
                restrict.assert_not_called()

    def test_output_tree_rejects_linked_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            linked = root / "output"
            try:
                linked.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Directory symlinks unavailable: {error}")
            with patch.object(sft_data, "OUTPUT", linked / "sft"), \
                    self.assertRaisesRegex(ValueError, "symbolic links or junctions"):
                sft_data.private_output()
            self.assertFalse((target / "sft").exists())

    def test_bad_rows_are_counted_and_a_short_reply_can_be_valid(self):
        long_reply = "We can reserve the conference room through Friday afternoon"
        fixture = [
            {"conversation": "Is room C free?", "reply": "Yes."},
            {"conversation": "IS ROOM C FREE?", "reply": " yes.  "},
            {"conversation": "  ", "reply": "Yes"},
            {"conversation": "A message.", "reply": None},
            {"conversation": f"An earlier answer: {long_reply}", "reply": long_reply},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            path.write_text("invalid\n" + "\n".join(map(json.dumps, fixture)), encoding="utf-8")
            rows, counts, digest = load_pairs(path)
            self.assertEqual(digest, load_pairs(path)[2])
        self.assertEqual([(row.line, row.reply) for row in rows], [(2, "Yes.")])
        self.assertEqual(counts, {"malformed": 2, "empty": 1, "duplicate": 1, "target_in_conversation": 1})

    def test_related_and_cross_quoted_replies_stay_together(self):
        original = "The side door by the small courtyard is closed until the painting crew leaves on Friday"
        answer = "Visitors can pick up a spare key from the front desk"
        rows = [
            ReplyPair(1, original, answer),
            ReplyPair(2, f"Hello there. {original} Let me know.", "Thanks"),
            ReplyPair(3, f"Could you confirm the note below?\n-----Original Message-----\n{answer}", "Of course"),
            ReplyPair(4, "Will you attend?", "Thanks"),
            ReplyPair(5, "What should I bring?", "Paper"),
        ]
        self.assertIn([1, 2, 3], [[row.line for row in group] for group in conversation_groups(rows)])
        splits = split_pairs(rows, 123)
        self.assertEqual(splits, split_pairs(rows, 123))
        self.assertTrue(any({1, 2, 3} <= {row.line for row in split} for split in splits.values()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "split.json"
            digest = "1" * 64
            split_hash = save_split(path, splits, digest, 123)
            self.assertEqual(split_hash, save_split(path, splits, digest, 123))
            self.assertNotIn(original, path.read_text(encoding="utf-8"))
            loaded_splits, manifest, loaded_hash = load_frozen_split(path, rows, digest)
            self.assertEqual(loaded_splits, splits)
            self.assertEqual(loaded_hash, split_hash)
            self.assertEqual(manifest["seed"], 123)
            with self.assertRaisesRegex(ValueError, "does not match"):
                save_split(path, splits, digest, 124)
            with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
                load_frozen_split(path, rows, "2" * 64)
