"""Load ``config/mailboxes.json``: the server address and the closed set of local accounts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_RELATIVE = Path("config") / "mailboxes.json"


@dataclass(frozen=True)
class Account:
    address: str
    name: str
    persona: str | None = None
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MailConfig:
    host: str
    smtp_port: int
    imap_port: int
    authserv_id: str
    password: str
    accounts: dict[str, Account]

    def account(self, address: str) -> Account | None:
        return self.accounts.get(address.strip().lower())

    def persona_account(self, client_id: str) -> Account:
        for account in self.accounts.values():
            if account.persona == client_id:
                return account
        raise KeyError(f"No mailbox is configured for persona {client_id}.")

    def check_login(self, user: str, password: str) -> str | None:
        """Return the canonical address when the credentials are valid."""
        account = self.account(user)
        return account.address if account and password == self.password else None


def load_config(root: Path, **overrides: Any) -> MailConfig:
    data = json.loads((root / CONFIG_RELATIVE).read_text(encoding="utf-8"))
    server = {**data["server"], **{k: v for k, v in overrides.items() if v is not None}}
    accounts = {
        address.lower(): Account(address=address.lower(), name=spec.get("name", address),
                                 persona=spec.get("persona"), facts=spec.get("facts", {}))
        for address, spec in data["accounts"].items()
    }
    return MailConfig(host=server["host"], smtp_port=int(server["smtp_port"]),
                      imap_port=int(server["imap_port"]), authserv_id=server["authserv_id"],
                      password=server["shared_password"], accounts=accounts)
