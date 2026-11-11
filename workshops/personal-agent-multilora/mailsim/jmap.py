"""A small JMAP (RFC 8620 / 8621) subset server for the PersonaDesk mailbox playground.

What it is: an in-repo stand-in for the mailbox features the playground proposal wanted from
Stalwart (separate accounts, threads, keywords, folders, drafts, search) built on the standard
library so it runs where Docker cannot. What it is not: Stalwart, a mail transfer agent, or an
Exchange emulator. It speaks plain JMAP, so ``JmapClient`` and the ``mail_*`` tools are
written against the protocol, not against this class. Whether real Stalwart accepts the same
calls has not been tested.

Deliberate limits:

* Loopback only. The constructor refuses any other bind address.
* No ``urn:ietf:params:jmap:submission`` capability and no ``EmailSubmission`` methods, and no
  SMTP relay: nothing here can send mail.
* ``Email/set`` can create only drafts (``$draft`` in the Drafts mailbox). Mail enters an
  account through ``Email/import``, which the operator's importer uses.
* One account per credential; an ``accountId`` that is not the caller's is ``accountNotFound``,
  and email, thread, and blob IDs are looked up inside the caller's account only.
"""

from __future__ import annotations

import base64
import hmac
import json
import re
import secrets
import threading
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime, formataddr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import MailConfig
from .jmapstore import JmapStore, StoreError, tokens

CORE = "urn:ietf:params:jmap:core"
MAIL = "urn:ietf:params:jmap:mail"
MAX_OBJECTS = 50
MAX_REQUEST_BYTES = 1_000_000
MAX_UPLOAD_BYTES = 10_000_000
MAX_CALLS = 16
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_KEYWORD = re.compile(r"^[\x21-\x7e]{1,255}$")
_KEYWORD_FORBIDDEN = set('(){]%*"\\/')
DRAFT_HEADER_PREFIX = "x-personadesk-"

EMAIL_PROPERTIES = (
    "id", "blobId", "threadId", "mailboxIds", "keywords", "size", "receivedAt", "messageId",
    "inReplyTo", "references", "from", "to", "cc", "subject", "sentAt", "preview",
    "hasAttachment", "bodyValues", "textBody", "attachments",
)


class MethodError(Exception):
    def __init__(self, kind: str, description: str = ""):
        super().__init__(description or kind)
        self.kind = kind
        self.description = description


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(value))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp()
    except ValueError as exc:
        raise MethodError("invalidArguments", f"Bad UTCDate {value!r}.") from exc


def _keyword(value: str) -> str:
    if not isinstance(value, str) or not _KEYWORD.match(value) \
            or any(ch in _KEYWORD_FORBIDDEN for ch in value):
        raise StoreError("invalidProperties", f"Invalid keyword {value!r}.")
    return value.lower()


def _people(entries: list[dict[str, str]]) -> str:
    return " ".join(f"{p['name']} {p['email']}" for p in entries)


# ---- filters --------------------------------------------------------------------------
def _matches(email: dict[str, Any], flt: dict[str, Any]) -> bool:
    if "operator" in flt:
        results = [_matches(email, c) for c in flt.get("conditions", [])]
        op = flt["operator"]
        if op == "AND":
            return all(results)
        if op == "OR":
            return any(results)
        if op == "NOT":
            return not any(results)
        raise MethodError("unsupportedFilter", f"Unknown operator {op!r}.")
    for key, want in flt.items():
        if key == "inMailbox":
            ok = want in email["mailboxIds"]
        elif key == "inMailboxOtherThan":
            ok = any(box not in want for box in email["mailboxIds"])
        elif key == "before":
            ok = email["receivedAt"] < _parse_utc(want)
        elif key == "after":
            ok = email["receivedAt"] >= _parse_utc(want)
        elif key == "minSize":
            ok = email["size"] >= want
        elif key == "maxSize":
            ok = email["size"] < want
        elif key == "hasKeyword":
            ok = str(want).lower() in email["keywords"]
        elif key == "notKeyword":
            ok = str(want).lower() not in email["keywords"]
        elif key == "hasAttachment":
            ok = bool(email["attachments"]) == bool(want)
        elif key == "text":
            ok = tokens(str(want)) <= tokens(" ".join([
                email["subject"], _people(email["from"]), _people(email["to"]),
                _people(email["cc"]), email["body"]]))
        elif key == "from":
            ok = tokens(str(want)) <= tokens(_people(email["from"]))
        elif key == "to":
            ok = tokens(str(want)) <= tokens(_people(email["to"]))
        elif key == "cc":
            ok = tokens(str(want)) <= tokens(_people(email["cc"]))
        elif key == "subject":
            ok = tokens(str(want)) <= tokens(email["subject"])
        elif key == "body":
            ok = tokens(str(want)) <= tokens(email["body"])
        else:
            raise MethodError("unsupportedFilter", f"Filter {key!r} is not supported.")
        if not ok:
            return False
    return True


def _resolve_pointer(value: Any, path: str) -> Any:
    wildcard = False
    current = [value]
    for part in (p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]):
        step = []
        for item in current:
            if part == "*":
                wildcard = True
                if not isinstance(item, list):
                    raise MethodError("invalidResultReference", "Wildcard needs an array.")
                step.extend(item)
            elif isinstance(item, dict) and part in item:
                step.append(item[part])
            elif isinstance(item, list) and part.isdigit() and int(part) < len(item):
                step.append(item[int(part)])
            else:
                raise MethodError("invalidResultReference", f"Cannot resolve {path!r}.")
        current = step
    if not wildcard:
        return current[0]
    flat: list[Any] = []
    for item in current:
        flat.extend(item if isinstance(item, list) else [item])
    return flat


class JmapApi:
    """Protocol logic, independent of HTTP so tests can call it directly."""

    def __init__(self, store: JmapStore, config: MailConfig, base_url: str = ""):
        self.store = store
        self.config = config
        self.base_url = base_url
        self.methods = {
            "Core/echo": self._echo,
            "Mailbox/get": self._mailbox_get,
            "Mailbox/query": self._mailbox_query,
            "Email/query": self._email_query,
            "Email/get": self._email_get,
            "Email/set": self._email_set,
            "Email/import": self._email_import,
            "Thread/get": self._thread_get,
        }

    # ---- session and request envelope ------------------------------------------------
    def session(self, address: str) -> dict[str, Any]:
        account_id = self.store.ensure_account(address)
        return {
            "capabilities": {
                CORE: {"maxSizeUpload": MAX_UPLOAD_BYTES, "maxConcurrentUpload": 4,
                       "maxSizeRequest": MAX_REQUEST_BYTES, "maxConcurrentRequests": 4,
                       "maxCallsInRequest": MAX_CALLS, "maxObjectsInGet": MAX_OBJECTS,
                       "maxObjectsInSet": MAX_OBJECTS, "collationAlgorithms": []},
                MAIL: {"maxMailboxesPerEmail": None, "maxSizeAttachmentsPerEmail": MAX_UPLOAD_BYTES,
                       "emailQuerySortOptions": ["receivedAt", "sentAt", "subject"]},
            },
            "accounts": {account_id: {"name": address, "isPersonal": True, "isReadOnly": False,
                                      "accountCapabilities": {MAIL: {}}}},
            "primaryAccounts": {MAIL: account_id},
            "username": address,
            "apiUrl": f"{self.base_url}/jmap/api",
            "downloadUrl": self.base_url + "/jmap/download/{accountId}/{blobId}/{name}",
            "uploadUrl": self.base_url + "/jmap/upload/{accountId}/",
            "state": self.store.state(account_id),
        }

    def handle(self, address: str, request: Any) -> dict[str, Any]:
        account_id = self.store.ensure_account(address)
        calls = request.get("methodCalls")
        if not isinstance(calls, list) or not all(
                isinstance(c, list) and len(c) == 3 for c in calls):
            raise MethodError("notRequest", "methodCalls must be a list of [name, args, id].")
        if len(calls) > MAX_CALLS:
            raise MethodError("limit", f"At most {MAX_CALLS} method calls per request.")
        responses: list[list[Any]] = []
        for name, args, call_id in calls:
            try:
                if name not in self.methods:
                    raise MethodError("unknownMethod", f"{name} is not supported.")
                if not isinstance(args, dict):
                    raise MethodError("invalidArguments", "Arguments must be an object.")
                resolved = self._resolve_refs(args, responses)
                if resolved.get("accountId") != account_id:
                    raise MethodError("accountNotFound", "Unknown account.")
                # Keep state checks and read-modify-write operations in one critical section.
                with self.store.lock:
                    result = self.methods[name](account_id, address, resolved)
                responses.append([name, result, call_id])
            except MethodError as exc:
                responses.append(["error", {"type": exc.kind, "description": exc.description},
                                  call_id])
            except StoreError as exc:
                responses.append(["error", {"type": exc.kind, "description": str(exc)}, call_id])
        return {"methodResponses": responses, "sessionState": self.store.state(account_id)}

    @staticmethod
    def _resolve_refs(args: dict[str, Any], responses: list[list[Any]]) -> dict[str, Any]:
        out = {}
        for key, value in args.items():
            if not key.startswith("#"):
                out[key] = value
                continue
            ref = value if isinstance(value, dict) else {}
            match = next((r for r in responses if r[2] == ref.get("resultOf")
                          and r[0] == ref.get("name")), None)
            if match is None or key[1:] in args:
                raise MethodError("invalidResultReference", f"Cannot resolve {key}.")
            out[key[1:]] = _resolve_pointer(match[1], str(ref.get("path", "")))
        return out

    # ---- methods ---------------------------------------------------------------------
    def _echo(self, account_id: str, address: str, args: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in args.items() if k != "accountId"}

    def _mailbox_get(self, account_id, address, args):
        boxes = self.store.mailboxes(account_id)
        ids = args.get("ids")
        found = [b for b in boxes if ids is None or b["id"] in ids]
        missing = [i for i in (ids or []) if i not in {b["id"] for b in boxes}]
        return {"accountId": account_id, "state": self.store.state(account_id), "list": found,
                "notFound": missing}

    def _mailbox_query(self, account_id, address, args):
        flt = args.get("filter") or {}
        boxes = [b for b in self.store.mailboxes(account_id)
                 if "role" not in flt or b["role"] == flt["role"]]
        return {"accountId": account_id, "queryState": self.store.state(account_id),
                "canCalculateChanges": False, "position": 0,
                "ids": [b["id"] for b in boxes], "total": len(boxes)}

    def _email_query(self, account_id, address, args):
        emails = [e for e in self.store.all_emails(account_id)
                  if _matches(e, args.get("filter") or {})]
        sort = (args.get("sort") or [{"property": "receivedAt", "isAscending": False}])[0]
        prop = sort.get("property", "receivedAt")
        keys = {"receivedAt": lambda e: e["receivedAt"], "sentAt": lambda e: e["sentAt"] or "",
                "subject": lambda e: e["subject"].casefold()}
        if prop not in keys:
            raise MethodError("unsupportedSort", f"Cannot sort by {prop!r}.")
        ascending = bool(sort.get("isAscending", True))
        emails.sort(key=lambda e: e["id"])
        emails.sort(key=keys[prop], reverse=not ascending)
        position = max(0, int(args.get("position") or 0))
        limit = args.get("limit")
        if limit is not None and int(limit) < 0:
            raise MethodError("invalidArguments", "limit must not be negative.")
        capped = min(int(limit), MAX_OBJECTS) if limit is not None else MAX_OBJECTS
        out = {"accountId": account_id, "queryState": self.store.state(account_id),
               "canCalculateChanges": False, "position": position,
               "ids": [e["id"] for e in emails[position:position + capped]]}
        if args.get("calculateTotal"):
            out["total"] = len(emails)
        if limit is None or int(limit) > MAX_OBJECTS:
            out["limit"] = MAX_OBJECTS
        return out

    def _email_json(self, e: dict[str, Any], props: tuple[str, ...] | list[str],
                    fetch_body: bool, max_bytes: int | None) -> dict[str, Any]:
        text = e["body"]
        truncated = False
        if max_bytes is not None and len(text.encode()) > max_bytes:
            text = text.encode()[:max_bytes].decode(errors="ignore")
            truncated = True
        full = {
            "id": e["id"], "blobId": e["blobId"], "threadId": e["threadId"],
            "mailboxIds": {m: True for m in e["mailboxIds"]},
            "keywords": {k: True for k in e["keywords"]}, "size": e["size"],
            "receivedAt": _utc(e["receivedAt"]), "messageId": [e["messageId"]],
            "inReplyTo": e["inReplyTo"] or None, "references": e["references"] or None,
            "from": e["from"] or None, "to": e["to"] or None, "cc": e["cc"] or None,
            "subject": e["subject"], "sentAt": e["sentAt"],
            "preview": " ".join(e["body"].split())[:256], "hasAttachment": bool(e["attachments"]),
            "bodyValues": ({"1": {"value": text, "isTruncated": truncated,
                                  "isEncodingProblem": False}} if fetch_body else {}),
            "textBody": [{"partId": "1", "type": "text/plain", "size": len(e["body"].encode())}],
            "attachments": [{"blobId": a["blobId"], "name": a["name"], "type": a["type"],
                             "size": a["size"], "disposition": "attachment"}
                            for a in e["attachments"]],
        }
        out: dict[str, Any] = {}
        for prop in props:
            if prop in full:
                out[prop] = full[prop]
            elif prop.startswith("header:"):
                parts = prop.split(":")
                if len(parts) not in (2, 3) or (len(parts) == 3 and parts[2] != "asText"):
                    raise MethodError("invalidArguments", f"Unsupported header form {prop!r}.")
                out[prop] = e["headers"].get(parts[1].lower())
            else:
                raise MethodError("invalidArguments", f"Unknown property {prop!r}.")
        return out

    def _email_get(self, account_id, address, args):
        ids = args.get("ids")
        if not isinstance(ids, list):
            raise MethodError("invalidArguments", "ids is required.")
        if len(ids) > MAX_OBJECTS:
            raise MethodError("requestTooLarge", f"At most {MAX_OBJECTS} ids per Email/get.")
        props = args.get("properties") or [p for p in EMAIL_PROPERTIES]
        fetch = bool(args.get("fetchTextBodyValues") or args.get("fetchAllBodyValues"))
        found, missing = [], []
        for email_id in ids:
            e = self.store.get_email(account_id, email_id) if isinstance(email_id, str) else None
            if e is None:
                missing.append(email_id)
            else:
                found.append(self._email_json(e, props, fetch, args.get("maxBodyValueBytes")))
        return {"accountId": account_id, "state": self.store.state(account_id), "list": found,
                "notFound": missing}

    def _thread_get(self, account_id, address, args):
        ids = args.get("ids")
        if not isinstance(ids, list):
            raise MethodError("invalidArguments", "ids is required.")
        if len(ids) > MAX_OBJECTS:
            raise MethodError("requestTooLarge", f"At most {MAX_OBJECTS} ids per Thread/get.")
        found, missing = [], []
        for thread_id in dict.fromkeys(ids):
            members = self.store.thread_email_ids(account_id, thread_id) \
                if isinstance(thread_id, str) else None
            if members is None:
                missing.append(thread_id)
            else:
                found.append({"id": thread_id, "emailIds": members})
        return {"accountId": account_id, "state": self.store.state(account_id), "list": found,
                "notFound": missing}

    def _email_import(self, account_id, address, args):
        emails = args.get("emails")
        if not isinstance(emails, dict) or len(emails) > MAX_OBJECTS:
            raise MethodError("invalidArguments", "emails must be an object of <= 50 entries.")
        self._check_state(account_id, args)
        old = self.store.state(account_id)
        created, not_created = {}, {}
        for cid, spec in emails.items():
            try:
                blob = self.store.get_blob(account_id, str(spec.get("blobId")))
                if blob is None:
                    raise StoreError("blobNotFound", "Unknown blobId for this account.")
                received = _parse_utc(spec["receivedAt"]) if spec.get("receivedAt") else None
                created[cid] = self.store.import_message(
                    account_id, blob[0], [m for m, v in (spec.get("mailboxIds") or {}).items() if v],
                    [_keyword(k) for k, v in (spec.get("keywords") or {}).items() if v],
                    received)
            except StoreError as exc:
                not_created[cid] = {"type": exc.kind, "description": str(exc)}
        return {"accountId": account_id, "oldState": old, "newState": self.store.state(account_id),
                "created": created or None, "notCreated": not_created or None}

    def _check_state(self, account_id: str, args: dict[str, Any]) -> None:
        expected = args.get("ifInState")
        if expected is not None and expected != self.store.state(account_id):
            raise MethodError("stateMismatch", "The account changed since ifInState.")

    def _email_set(self, account_id, address, args):
        create = args.get("create") or {}
        update = args.get("update") or {}
        destroy = args.get("destroy") or []
        if not isinstance(create, dict) or not isinstance(update, dict) \
                or not isinstance(destroy, list):
            raise MethodError("invalidArguments", "create/update are objects; destroy is a list.")
        if len(create) + len(update) + len(destroy) > MAX_OBJECTS:
            raise MethodError("requestTooLarge", f"At most {MAX_OBJECTS} objects per Email/set.")
        self._check_state(account_id, args)
        old = self.store.state(account_id)
        out: dict[str, Any] = {"accountId": account_id, "oldState": old}
        created, not_created, updated, not_updated = {}, {}, {}, {}
        destroyed, not_destroyed = [], {}
        for cid, obj in create.items():
            try:
                created[cid] = self._create_draft(account_id, address, obj)
            except (StoreError, ValueError, KeyError, TypeError, AttributeError) as exc:
                kind = exc.kind if isinstance(exc, StoreError) else "invalidProperties"
                not_created[cid] = {"type": kind, "description": str(exc) or type(exc).__name__}
        for email_id, patch in update.items():
            try:
                email = self.store.get_email(account_id, email_id)
                if email is None:
                    raise StoreError("notFound", "No such email.")
                keywords, boxes = self._apply_patch(email, patch)
                self.store.update_email(account_id, email_id, keywords, boxes)
                updated[email_id] = None
            except StoreError as exc:
                not_updated[email_id] = {"type": exc.kind, "description": str(exc)}
        for email_id in destroy:
            try:
                self.store.destroy_email(account_id, str(email_id))
                destroyed.append(email_id)
            except StoreError as exc:
                not_destroyed[str(email_id)] = {"type": exc.kind, "description": str(exc)}
        out.update({"newState": self.store.state(account_id), "created": created or None,
                    "notCreated": not_created or None, "updated": updated or None,
                    "notUpdated": not_updated or None, "destroyed": destroyed or None,
                    "notDestroyed": not_destroyed or None})
        return out

    @staticmethod
    def _apply_patch(email: dict[str, Any], patch: Any) -> tuple[list[str] | None,
                                                                  list[str] | None]:
        if not isinstance(patch, dict) or not patch:
            raise StoreError("invalidPatch", "The patch must be a non-empty object.")
        keywords, boxes = set(email["keywords"]), set(email["mailboxIds"])
        touched_kw = touched_box = False
        for key, value in patch.items():
            if key == "keywords":
                keywords = {_keyword(k) for k, v in (value or {}).items() if v is True}
                touched_kw = True
            elif key.startswith("keywords/"):
                name = _keyword(key[len("keywords/"):])
                if value is True:
                    keywords.add(name)
                elif value is None:
                    keywords.discard(name)
                else:
                    raise StoreError("invalidPatch", "A keyword patch value is true or null.")
                touched_kw = True
            elif key == "mailboxIds":
                boxes = {m for m, v in (value or {}).items() if v is True}
                touched_box = True
            elif key.startswith("mailboxIds/"):
                mailbox_id = key[len("mailboxIds/"):]
                if value is True:
                    boxes.add(mailbox_id)
                elif value is None:
                    boxes.discard(mailbox_id)
                else:
                    raise StoreError("invalidPatch", "A mailbox patch value is true or null.")
                touched_box = True
            else:
                raise StoreError("invalidProperties", f"Cannot update {key!r}.")
        return (sorted(keywords) if touched_kw else None,
                sorted(boxes) if touched_box else None)

    def _create_draft(self, account_id: str, address: str, obj: dict[str, Any]) -> dict[str, Any]:
        """Create an unsent draft. Anything that is not a draft is refused."""
        drafts = self.store.mailbox_by_role(account_id, "drafts")
        keywords = {_keyword(k) for k, v in (obj.get("keywords") or {}).items() if v}
        boxes = {m for m, v in (obj.get("mailboxIds") or {}).items() if v}
        if boxes != {drafts} or "$draft" not in keywords:
            raise StoreError("invalidProperties",
                             "Email/set can only create drafts: $draft in the Drafts mailbox.")
        recipients = obj.get("to") or []
        if not recipients:
            raise StoreError("invalidProperties", "A draft needs at least one recipient.")
        part = next(iter(obj.get("textBody") or []), {})
        value = (obj.get("bodyValues") or {}).get(part.get("partId"), {}).get("value")
        if not isinstance(value, str) or len(value) > 200_000:
            raise StoreError("invalidProperties", "A draft needs a text body of <= 200000 chars.")
        msg = EmailMessage(policy=policy.SMTP)
        account = self.config.account(address)
        msg["From"] = formataddr((account.name if account else "", address))  # never spoofable
        msg["To"] = ", ".join(formataddr((p.get("name", ""), p["email"])) for p in recipients)
        if obj.get("cc"):
            msg["Cc"] = ", ".join(formataddr((p.get("name", ""), p["email"])) for p in obj["cc"])
        msg["Subject"] = str(obj.get("subject") or "")
        msg["Date"] = format_datetime(datetime.now(UTC))
        # Not the fixture domain: the mail tools treat only fixture-domain messages as writable.
        msg["Message-ID"] = f"<{secrets.token_hex(12)}@generated.personadesk.test>"
        if obj.get("inReplyTo"):
            msg["In-Reply-To"] = " ".join(f"<{i}>" for i in obj["inReplyTo"])
        if obj.get("references"):
            msg["References"] = " ".join(f"<{i}>" for i in obj["references"])
        for key, header_value in obj.items():
            if key.startswith("header:"):
                name = key.split(":")[1]
                if not name.lower().startswith(DRAFT_HEADER_PREFIX):
                    raise StoreError("invalidProperties", f"Header {name} is not settable.")
                msg[name] = str(header_value)
        msg.set_content(value)
        for att in obj.get("attachments") or []:
            blob = self.store.get_blob(account_id, str(att.get("blobId")))
            if blob is None:
                raise StoreError("blobNotFound", "Attachment blob is not in this account.")
            maintype, _, subtype = str(att.get("type") or blob[1]).partition("/")
            msg.add_attachment(blob[0], maintype=maintype or "application",
                               subtype=subtype or "octet-stream",
                               filename=str(att.get("name") or "attachment"))
        return self.store.import_message(account_id, msg.as_bytes(), [drafts],
                                         sorted(keywords | {"$draft"}))

    # ---- blobs ------------------------------------------------------------------------
    def upload(self, address: str, account_id: str, data: bytes, content_type: str) -> dict:
        if self.store.ensure_account(address) != account_id:
            raise MethodError("accountNotFound", "Unknown account.")
        blob_id = self.store.put_blob(account_id, data, content_type)
        return {"accountId": account_id, "blobId": blob_id, "type": content_type,
                "size": len(data)}

    def download(self, address: str, account_id: str, blob_id: str):
        if self.store.ensure_account(address) != account_id:
            return None
        return self.store.get_blob(account_id, blob_id)


# ---- HTTP -----------------------------------------------------------------------------
class JmapServer:
    """Serve the API on loopback in a background thread (port 0 picks a free port)."""

    def __init__(self, config: MailConfig, db_path: Path, host: str | None = None,
                 port: int | None = None):
        self.config = config
        self.db_path = db_path
        self.host = host or config.host
        if self.host not in LOOPBACK:
            raise ValueError("The JMAP playground binds to loopback only.")
        self.port = config.jmap_port if port is None else port
        self.store: JmapStore | None = None
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def authenticate(self, header: str | None) -> str | None:
        if not header or not header.startswith("Basic "):
            return None
        try:
            user, _, password = base64.b64decode(header[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return None
        account = self.config.account(user)
        if account and hmac.compare_digest(password.encode(), self.config.password.encode()):
            return account.address
        return None

    def start(self) -> JmapServer:
        self.store = JmapStore(self.db_path)
        server = self
        outer_api: list[JmapApi] = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"  # one request per connection: no unread-body desync

            def log_message(self, *_args: Any) -> None:  # keep test and CLI output quiet
                pass

            def _send(self, status: int, payload: Any, ctype: str = "application/json",
                      extra: dict[str, str] | None = None) -> None:
                body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _problem(self, status: int, kind: str, detail: str) -> None:
                self._send(status, {"type": f"urn:ietf:params:jmap:error:{kind}",
                                    "status": status, "detail": detail},
                           "application/problem+json")

            def _auth(self) -> str | None:
                allowed = {f"127.0.0.1:{server.port}", f"localhost:{server.port}",
                           f"[::1]:{server.port}"}
                if self.headers.get("Host") not in allowed:  # DNS-rebinding guard
                    self._problem(421, "forbidden", "Unexpected Host header.")
                    return None
                address = server.authenticate(self.headers.get("Authorization"))
                if address is None:
                    self._send(401, {"type": "about:blank", "status": 401, "detail": "Login"},
                               "application/problem+json",
                               {"WWW-Authenticate": 'Basic realm="jmap"'})
                return address

            def _read(self, limit: int) -> bytes | None:
                length = int(self.headers.get("Content-Length") or 0)
                if length > limit:
                    self._problem(413, "limit", "Body too large.")
                    return None
                return self.rfile.read(length)

            def do_GET(self) -> None:
                address = self._auth()
                if address is None:
                    return
                path = urlparse(self.path).path
                api = outer_api[0]
                if path in ("/.well-known/jmap", "/jmap/session"):
                    self._send(200, api.session(address))
                elif path.startswith("/jmap/download/"):
                    parts = path.split("/")[3:]
                    if len(parts) < 2:
                        self._problem(404, "notFound", "Bad download URL.")
                        return
                    blob = api.download(address, parts[0], parts[1])
                    if blob is None:
                        self._problem(404, "notFound", "No such blob.")
                        return
                    name = unquote(parts[2]) if len(parts) > 2 else "blob"
                    safe = re.sub(r'[^\w.\- ]', "_", name)
                    self._send(200, blob[0], "application/octet-stream",
                               {"Content-Disposition": f'attachment; filename="{safe}"',
                                "X-Blob-Type": blob[1]})
                else:
                    self._problem(404, "notFound", "Unknown path.")

            def do_POST(self) -> None:
                address = self._auth()
                if address is None:
                    return
                api = outer_api[0]
                path = urlparse(self.path).path
                if path == "/jmap/api":
                    raw = self._read(MAX_REQUEST_BYTES)
                    if raw is None:
                        return
                    try:
                        request = json.loads(raw)
                        if not isinstance(request, dict):
                            raise TypeError("not an object")
                    except (ValueError, TypeError):
                        self._problem(400, "notJSON", "The body is not a JSON object.")
                        return
                    if not set(request.get("using") or []) <= {CORE, MAIL}:
                        self._problem(400, "unknownCapability",
                                      "Only core and mail are supported; there is no submission.")
                        return
                    try:
                        self._send(200, api.handle(address, request))
                    except MethodError as exc:
                        self._problem(400, exc.kind, exc.description)
                elif path.startswith("/jmap/upload/"):
                    raw = self._read(MAX_UPLOAD_BYTES)
                    if raw is None:
                        return
                    account_id = path.split("/")[3] if len(path.split("/")) > 3 else ""
                    try:
                        self._send(201, api.upload(
                            address, account_id, raw,
                            self.headers.get("Content-Type", "application/octet-stream")))
                    except MethodError:
                        self._problem(404, "notFound", "Unknown account.")
                else:
                    self._problem(404, "notFound", "Unknown path.")

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self.port = self._httpd.server_address[1]
        outer_api.append(JmapApi(self.store, self.config, self.base_url))
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread:
            self._thread.join(10)
        if self.store:
            self.store.close()
