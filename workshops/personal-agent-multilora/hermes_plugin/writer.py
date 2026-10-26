"""Draft writer clients.

The writer owns exactly one thing: base + persona adapter selection and reply text. It has no
tools, memory, or approval power. ``http`` talks to ``scripts/writer_service.py`` (or any
service with the same contract) on loopback. ``template`` is the deterministic E0 baseline and
always labels itself, so a template draft can never be mistaken for an adapter draft.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import requests


class WriterUnavailable(Exception):
    pass


class Writer(Protocol):
    def generate(
        self, *, client_id: str, adapter: str, subject: str, body: str, brief: list[str]
    ) -> tuple[str, dict[str, Any]]: ...


@dataclass
class HttpWriter:
    base_url: str = "http://127.0.0.1:8100"
    timeout: float = 120.0

    def generate(self, *, client_id, adapter, subject, body, brief):
        try:
            response = requests.post(
                f"{self.base_url.rstrip('/')}/v1/draft",
                json={"client_id": client_id, "adapter": adapter, "subject": subject,
                      "body": body, "brief": brief},
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise WriterUnavailable(f"Writer service unavailable: {exc}") from exc
        if data.get("client_id") != client_id or data.get("adapter") != adapter:
            raise WriterUnavailable("Writer answered with a different persona or adapter.")
        text = data.get("text")
        if not isinstance(text, str) or not text.strip():
            raise WriterUnavailable("Writer returned an empty draft.")
        identity = {
            "backend": "http",
            "base_model": data.get("base_model"),
            "base_revision": data.get("base_revision"),
            "adapter": adapter,
            "adapter_revision": data.get("adapter_revision"),
            "adapted": bool(data.get("adapted", True)),
        }
        return text.strip(), identity


@dataclass
class TemplateWriter:
    """Deterministic E0 writer: restates verified check outcomes, never invents facts."""

    signature: str = "PersonaDesk draft"

    def generate(self, *, client_id, adapter, subject, body, brief):
        lines = [
            "Hello,",
            "",
            f"Thank you for your message about \"{subject}\".",
            "",
            *[f"- {item}" for item in brief],
            "",
            "Best regards,",
            self.signature,
        ]
        return "\n".join(lines), {"backend": "template", "adapter": None, "adapted": False}


def make_writer(settings: dict[str, Any]) -> Writer:
    backend = settings.get("writer_backend", "http")
    if backend == "http":
        return HttpWriter(
            base_url=settings.get("writer_url", "http://127.0.0.1:8100"),
            timeout=float(settings.get("writer_timeout_seconds", 120)),
        )
    if backend == "template":
        return TemplateWriter()
    raise ValueError(f"Unknown writer_backend '{backend}'.")
