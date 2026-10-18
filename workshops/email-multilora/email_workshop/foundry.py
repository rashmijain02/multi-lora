from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests
from dotenv import load_dotenv

from email_workshop.data import LABELS, messages
from email_workshop.evaluation import parse_labels


class FoundryError(RuntimeError):
    """A sanitized upstream failure, without email text or credentials."""


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "REPLACE_ME" or value.startswith("REPLACE_WITH_"):
        raise ValueError(f"Set {name} to a non-placeholder value.")
    return value


@dataclass(frozen=True)
class FoundryConfig:
    url: str
    model: str
    api_key: str = field(repr=False)
    api_version: str = ""

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.path.endswith("/chat/completions")
        ):
            raise ValueError(
                "Use the exact HTTPS chat/completions URL without query or credentials."
            )
        if not self.model.strip() or not self.api_key.strip():
            raise ValueError("Foundry model and API key must not be empty.")

    @classmethod
    def from_env(cls, *, load_env: bool = True) -> FoundryConfig:
        # Resolve .env relative to the explicit working directory, not an ancestor.
        if load_env:
            load_dotenv(dotenv_path=".env", override=False)
        if os.environ.get("ALLOW_REMOTE_EMAIL", "").lower() != "true":
            raise ValueError("Set ALLOW_REMOTE_EMAIL=true only after approving remote processing.")
        return cls(
            required("FOUNDRY_CHAT_COMPLETIONS_URL"),
            required("FOUNDRY_MODEL"),
            required("FOUNDRY_API_KEY"),
            os.environ.get("FOUNDRY_API_VERSION", "").strip(),
        )


class FoundryClassifier:
    def __init__(self, config: FoundryConfig):
        self.config = config

    def classify(self, subject: str, body: str) -> list[str]:
        try:
            response = requests.post(
                self.config.url,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                params={"api-version": self.config.api_version} if self.config.api_version else {},
                json={
                    "model": self.config.model,
                    "messages": messages(subject, body, LABELS),
                    "temperature": 0,
                    "max_tokens": 256,
                    "stream": False,
                },
                timeout=(10, 90),
                allow_redirects=False,
            )
        except requests.RequestException:
            raise FoundryError(
                "Foundry transport failed; check connectivity and timeout."
            ) from None
        if response.status_code != 200:
            raise FoundryError(f"Foundry returned HTTP {response.status_code}.")
        try:
            choice = response.json()["choices"][0]
            if not isinstance(choice, dict) or choice.get("finish_reason") != "stop":
                raise ValueError("Incomplete or filtered response.")
            return parse_labels(choice["message"]["content"], LABELS)
        except (KeyError, IndexError, TypeError, ValueError):
            raise FoundryError(
                "Foundry returned incomplete or invalid classification JSON."
            ) from None
