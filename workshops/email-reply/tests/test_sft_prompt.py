import unittest

from util.prompts import Hardware, ModelProfile, prepare_prompt, supervised_example


class CharacterTokenizer:
    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        return "".join(f"[{m['role']}]{m['content']}</end>" for m in messages) + (
            "[assistant]" if add_generation_prompt else "\n"
        )

    def encode(self, text, *, add_special_tokens):
        return [ord(c) for c in text.replace("</end>", "\0")]


class ReplyPromptTests(unittest.TestCase):
    def test_budget_and_supervision_are_independent_of_target(self):
        tokenizer = CharacterTokenizer()
        hardware = Hardware(max_length=210, completion_tokens=15)
        model = ModelProfile(end_token="</end>")
        conversation = "Latest request.\n" + "Older quote. " * 20
        prompt = prepare_prompt(tokenizer, hardware, conversation)
        self.assertTrue(prompt.truncated)
        self.assertTrue(prompt.conversation.startswith("Latest request."))
        self.assertLessEqual(len(prompt.ids), 195)
        example = supervised_example(tokenizer, model, hardware, prompt, "Yes.")
        self.assertEqual(example["input_ids"][:len(prompt.ids)], list(prompt.ids))
        self.assertEqual(example["labels"][:len(prompt.ids)], [-100] * len(prompt.ids))
        self.assertEqual(example["labels"][len(prompt.ids):], [ord(c) for c in "Yes.\0"])
        self.assertIsNone(supervised_example(tokenizer, model, hardware, prompt, "This reply will not fit"))
