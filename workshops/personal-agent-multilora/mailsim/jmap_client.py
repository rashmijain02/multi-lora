"""A plain JMAP client (RFC 8620 / 8621) built on ``requests``.

It discovers everything from the authenticated session (account ID, API, upload, and download
URLs) and never hardcodes them. A method-level ``error`` response raises ``JmapError`` so a
failure cannot be mistaken for an empty result. Nothing here can send mail: the client only
issues the Mailbox, Email, and Thread methods.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests

CORE = "urn:ietf:params:jmap:core"
MAIL = "urn:ietf:params:jmap:mail"


class JmapError(Exception):
    """A JMAP method-level or request-level error."""

    def __init__(self, kind: str, description: str = ""):
        super().__init__(f"{kind}: {description}" if description else kind)
        self.kind = kind
        self.description = description


class JmapClient:
    def __init__(self, base_url: str, user: str, password: str, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.http = requests.Session()
        self.http.auth = (user, password)
        self._session: dict[str, Any] | None = None

    def session(self, refresh: bool = False) -> dict[str, Any]:
        if self._session is None or refresh:
            response = self.http.get(f"{self.base_url}/.well-known/jmap", timeout=self.timeout)
            self._raise_for(response)
            self._session = response.json()
        return self._session

    @property
    def account_id(self) -> str:
        return self.session()["primaryAccounts"][MAIL]

    @staticmethod
    def _raise_for(response: requests.Response) -> None:
        if response.status_code >= 400:
            try:
                problem = response.json()
                raise JmapError(str(problem.get("type", response.status_code)),
                                str(problem.get("detail", "")))
            except ValueError:
                raise JmapError(f"http-{response.status_code}", response.text[:200]) from None

    def call(self, *calls: tuple[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Run method calls in one request; return each call's arguments, in order."""
        body = {"using": [CORE, MAIL],
                "methodCalls": [[name, args, f"c{i}"] for i, (name, args) in enumerate(calls)]}
        response = self.http.post(self.session()["apiUrl"], json=body, timeout=self.timeout)
        self._raise_for(response)
        results = []
        for name, args, _call_id in response.json()["methodResponses"]:
            if name == "error":
                raise JmapError(args.get("type", "error"), args.get("description", ""))
            results.append(args)
        return results

    def method(self, name: str, **args: Any) -> dict[str, Any]:
        return self.call((name, {"accountId": self.account_id, **args}))[0]

    # ---- conveniences ------------------------------------------------------------------
    def mailboxes(self) -> dict[str, str]:
        """Role -> mailbox ID, discovered from the server."""
        listing = self.method("Mailbox/get", ids=None)["list"]
        return {box["role"]: box["id"] for box in listing if box.get("role")}

    def query_all(self, flt: dict[str, Any] | None = None, page: int = 50) -> list[str]:
        ids: list[str] = []
        while True:
            result = self.method("Email/query", filter=flt or {}, position=len(ids), limit=page,
                                 sort=[{"property": "receivedAt", "isAscending": True}])
            ids.extend(result["ids"])
            if len(result["ids"]) < page:
                return ids

    def upload(self, data: bytes, content_type: str) -> str:
        url = self.session()["uploadUrl"].replace("{accountId}", self.account_id)
        response = self.http.post(url, data=data, headers={"Content-Type": content_type},
                                  timeout=self.timeout)
        self._raise_for(response)
        return response.json()["blobId"]

    def download(self, blob_id: str, name: str = "blob") -> bytes:
        url = (self.session()["downloadUrl"].replace("{accountId}", self.account_id)
               .replace("{blobId}", blob_id).replace("{name}", quote(name)))
        response = self.http.get(url, timeout=self.timeout)
        self._raise_for(response)
        return response.content
