"""Model profiles and shared prompt/completion preparation."""

import re
from dataclasses import dataclass
from typing import Protocol

INSTRUCTION = (
    "Draft a reply to the latest message using only the supplied conversation. "
    "Do not invent details. If essential information is missing, ask for it."
)


REVISION_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def format_model_ref(model_id: str, revision: str | None = None) -> str:
    if revision:
        short = revision[:12] if re.fullmatch(r"[0-9a-fA-F]{40}", revision) else revision
        return f"{model_id} @ {short}"
    return model_id


@dataclass(frozen=True)
class ModelProfile:
    model_id: str = "Qwen/Qwen3-4B-Instruct-2507"
    revision: str | None = None
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    end_token: str = "<|im_end|>"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", self.model_id):
            raise ValueError("Provide a Hugging Face model ID.")
        if self.revision is not None:
            if not isinstance(self.revision, str):
                raise ValueError("Model revision must be a string or None.")
            cleaned_rev = self.revision.strip()
            if not cleaned_rev:
                object.__setattr__(self, "revision", None)
            elif not REVISION_RE.fullmatch(cleaned_rev):
                raise ValueError("Model revision contains invalid characters.")
            else:
                object.__setattr__(self, "revision", cleaned_rev)
        cleaned = tuple(module.strip() for module in self.target_modules if module.strip())
        if not cleaned or len(set(cleaned)) != len(self.target_modules):
            raise ValueError("Provide unique, nonempty LoRA target modules.")
        object.__setattr__(self, "target_modules", cleaned)
        if not self.end_token:
            raise ValueError("LoRA targets and the model's end-of-turn token are required.")


@dataclass(frozen=True)
class Hardware:
    max_length: int = 2048
    completion_tokens: int = 384
    batch_size: int = 1
    accumulation: int = 8
    four_bit: bool = True
    bf16: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.completion_tokens < self.max_length:
            raise ValueError("Reserve a completion budget smaller than the context limit.")
        if min(self.batch_size, self.accumulation) < 1:
            raise ValueError("Batch and accumulation sizes must be positive.")


class ChatTokenizer(Protocol):
    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str: ...

    def encode(self, text: str, *, add_special_tokens: bool) -> list[int]: ...


@dataclass(frozen=True)
class Prompt:
    conversation: str
    ids: tuple[int, ...]
    truncated: bool


def render(
    tokenizer: ChatTokenizer,
    conversation: str,
    reply: str | None = None,
    *,
    instruction: str = INSTRUCTION,
) -> tuple[int, ...]:
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": conversation},
    ]
    if reply is not None:
        messages.append({"role": "assistant", "content": reply})
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=reply is None,
    )
    return tuple(tokenizer.encode(text, add_special_tokens=False))


def prepare_prompt(tokenizer: ChatTokenizer, hardware: Hardware, conversation: str) -> Prompt:
    # Conversations place the newest message first; trim older quoted history from the tail.
    budget = hardware.max_length - hardware.completion_tokens
    ids = render(tokenizer, conversation)
    if len(ids) <= budget:
        return Prompt(conversation, ids, False)
    low, high = 0, len(conversation)
    prefix = ""
    ids = render(tokenizer, prefix)
    if len(ids) >= budget:
        raise ValueError("The token budget cannot fit the chat template and instruction.")
    while low <= high:
        middle = (low + high) // 2
        candidate = conversation[:middle].rstrip()
        attempt = render(tokenizer, candidate)
        if len(attempt) <= budget:
            prefix, ids = candidate, attempt
            low = middle + 1
        else:
            high = middle - 1
    if not prefix:
        raise ValueError("The token budget cannot fit any conversation text.")
    return Prompt(prefix, ids, True)


def end_id(tokenizer: ChatTokenizer, model: ModelProfile) -> int:
    ids = tokenizer.encode(model.end_token, add_special_tokens=False)
    if len(ids) != 1:
        raise ValueError("The configured end-of-turn marker must be a single token.")
    return ids[0]


def supervised_example(
    tokenizer: ChatTokenizer,
    model: ModelProfile,
    hardware: Hardware,
    prompt: Prompt,
    reply: str,
) -> dict[str, list[int]] | None:
    full = render(tokenizer, prompt.conversation, reply)
    if full[: len(prompt.ids)] != prompt.ids:
        raise ValueError("The model template does not preserve the generation prompt as a prefix.")
    suffix = full[len(prompt.ids) :]
    token = end_id(tokenizer, model)
    if suffix.count(token) != 1 or suffix[0] == token:
        raise ValueError("Expected one nonempty assistant turn with an end-of-turn token.")
    completion = suffix[: suffix.index(token) + 1]
    if len(completion) > hardware.completion_tokens:
        return None
    return {
        "input_ids": list(prompt.ids + completion),
        "labels": [-100] * len(prompt.ids) + list(completion),
    }
