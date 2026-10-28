"""Minimal IMAP4rev1 server over the mailsim store (one INBOX per account).

Implements the subset used by Python ``imaplib`` clients, including the Hermes email
gateway: CAPABILITY, ID, LOGIN, SELECT/EXAMINE, LIST, STATUS, SEARCH, FETCH, STORE,
EXPUNGE, CLOSE, NOOP, LOGOUT and their ``UID`` forms. Literals sent by clients are not
supported; plaintext only (loopback lab use).
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from .config import MailConfig
from .store import MailStore

CAPABILITIES = "IMAP4rev1 ID UNSELECT"
SYSTEM_FLAGS = ("\\Seen", "\\Answered", "\\Flagged", "\\Deleted", "\\Draft")
_PARTIAL_RE = re.compile(r"<(\d+)(?:\.(\d+))?>$")


class IMAPError(Exception):
    """Respond ``BAD`` (``bad=True``) or ``NO`` to the current command."""

    def __init__(self, message: str, bad: bool = False):
        super().__init__(message)
        self.bad = bad


# ---- parsing -----------------------------------------------------------------------------
def tokenize(text: str) -> list[Any]:
    """Split IMAP arguments into atoms, quoted strings and nested lists.

    ``[...]`` sections stay attached to their atom so ``BODY.PEEK[HEADER.FIELDS (FROM)]<0.10>``
    is one token.
    """
    stack: list[list[Any]] = [[]]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == " ":
            i += 1
        elif c == "(":
            stack.append([])
            i += 1
        elif c == ")":
            if len(stack) == 1:
                raise IMAPError("Unbalanced parenthesis", bad=True)
            done = stack.pop()
            stack[-1].append(done)
            i += 1
        elif c == '"':
            i += 1
            out = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    i += 1
                out.append(text[i])
                i += 1
            if i >= n:
                raise IMAPError("Unterminated quoted string", bad=True)
            stack[-1].append("".join(out))
            i += 1
        elif c == "{":
            raise IMAPError("Client literals are not supported by mailsim", bad=True)
        else:
            start, depth = i, 0
            while i < n and (depth or text[i] not in " ()"):
                if text[i] == "[":
                    depth += 1
                elif text[i] == "]":
                    depth -= 1
                i += 1
            stack[-1].append(text[start:i])
    if len(stack) != 1:
        raise IMAPError("Unbalanced parenthesis", bad=True)
    return stack[0]


def resolve_set(spec: str, values: list[int]) -> set[int]:
    """Resolve a sequence set (``1:*``, ``2,4:6``) against the ordered ``values``."""
    if not values:
        return set()
    top = values[-1]
    chosen: set[int] = set()
    for part in spec.split(","):
        lo_s, _, hi_s = part.partition(":")
        try:
            lo = top if lo_s == "*" else int(lo_s)
            hi = lo if not hi_s else (top if hi_s == "*" else int(hi_s))
        except ValueError as exc:
            raise IMAPError(f"Bad sequence set {spec!r}", bad=True) from exc
        lo, hi = sorted((lo, hi))
        chosen.update(v for v in values if lo <= v <= hi)
    return chosen


def split_message(raw: bytes) -> tuple[bytes, bytes]:
    for sep in (b"\r\n\r\n", b"\n\n"):
        idx = raw.find(sep)
        if idx >= 0:
            return raw[: idx + len(sep)], raw[idx + len(sep):]
    return raw, b""


def header_fields(header: bytes, names: set[str], exclude: bool) -> bytes:
    lines = header.replace(b"\r\n", b"\n").split(b"\n")
    fields: list[list[bytes]] = []
    for line in lines:
        if not line:
            continue
        if line[:1] in (b" ", b"\t") and fields:
            fields[-1].append(line)
        else:
            fields.append([line])
    kept = []
    for field in fields:
        name = field[0].split(b":", 1)[0].decode("ascii", "replace").strip().upper()
        if (name in names) != exclude:
            kept.append(b"\r\n".join(field))
    return b"".join(f + b"\r\n" for f in kept) + b"\r\n"


def _internaldate(ts: float) -> str:
    return time.strftime('"%d-%b-%Y %H:%M:%S +0000"', time.gmtime(ts))


# ---- session -----------------------------------------------------------------------------
class IMAPSession:
    def __init__(self, config: MailConfig, store: MailStore, reader, writer):
        self.config, self.store, self.reader, self.writer = config, store, reader, writer
        self.user: str | None = None
        self.selected = False
        self.readonly = False

    def send(self, data: bytes | str) -> None:
        self.writer.write(data.encode("utf-8") if isinstance(data, str) else data)

    async def run(self) -> None:
        self.send(f"* OK [CAPABILITY {CAPABILITIES}] PersonaDesk mailsim IMAP ready\r\n")
        await self.writer.drain()
        while True:
            line = await self.reader.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            tag, _, rest = text.partition(" ")
            command, _, arg = rest.partition(" ")
            command = command.upper()
            uid = False
            if command == "UID":
                uid = True
                command, _, arg = arg.partition(" ")
                command = command.upper()
            try:
                handler = getattr(self, f"cmd_{command}", None)
                if not tag or handler is None or (uid and command not in
                                                   ("FETCH", "SEARCH", "STORE")):
                    raise IMAPError(f"Unknown command {command or '(empty)'}", bad=True)
                keep_going = await handler(tag, tokenize(arg), uid)
            except IMAPError as exc:
                self.send(f"{tag or '*'} {'BAD' if exc.bad else 'NO'} {exc}\r\n")
                keep_going = True
            await self.writer.drain()
            if keep_going is False:
                return

    def ok(self, tag: str, text: str) -> None:
        self.send(f"{tag} OK {text}\r\n")

    def _require_auth(self) -> str:
        if self.user is None:
            raise IMAPError("Log in first")
        return self.user

    def _require_selected(self) -> str:
        user = self._require_auth()
        if not self.selected:
            raise IMAPError("Select a mailbox first")
        return user

    @staticmethod
    def _inbox(name: Any) -> None:
        if not isinstance(name, str) or name.upper() != "INBOX":
            raise IMAPError("Only INBOX exists in mailsim")

    # -- any state
    async def cmd_CAPABILITY(self, tag, args, uid):
        self.send(f"* CAPABILITY {CAPABILITIES}\r\n")
        self.ok(tag, "CAPABILITY completed")

    async def cmd_NOOP(self, tag, args, uid):
        if self.selected:
            self.send(f"* {len(self.store.messages(self.user))} EXISTS\r\n")
        self.ok(tag, "NOOP completed")

    cmd_CHECK = cmd_NOOP

    async def cmd_ID(self, tag, args, uid):
        self.send('* ID ("name" "personadesk-mailsim" "version" "1")\r\n')
        self.ok(tag, "ID completed")

    async def cmd_LOGOUT(self, tag, args, uid):
        self.send("* BYE mailsim logging out\r\n")
        self.ok(tag, "LOGOUT completed")
        return False

    # -- authentication
    async def cmd_LOGIN(self, tag, args, uid):
        if len(args) != 2 or not all(isinstance(a, str) for a in args):
            raise IMAPError("LOGIN needs user and password", bad=True)
        address = self.config.check_login(args[0], args[1])
        if address is None:
            raise IMAPError("[AUTHENTICATIONFAILED] Invalid credentials")
        self.user = address
        self.ok(tag, f"[CAPABILITY {CAPABILITIES}] LOGIN completed")

    # -- mailbox
    async def _select(self, tag, args, readonly):
        user = self._require_auth()
        self._inbox(args[0] if args else None)
        messages = self.store.messages(user)
        box = self.store.status(user)
        unseen = [i + 1 for i, m in enumerate(messages) if "\\Seen" not in m["flags"]]
        self.send(f"* FLAGS ({' '.join(SYSTEM_FLAGS)})\r\n"
                  f"* OK [PERMANENTFLAGS ({' '.join(SYSTEM_FLAGS)})] Flags permitted\r\n"
                  f"* {len(messages)} EXISTS\r\n* 0 RECENT\r\n"
                  f"* OK [UIDVALIDITY {box['uidvalidity']}] UIDs valid\r\n"
                  f"* OK [UIDNEXT {box['uidnext']}] Predicted next UID\r\n")
        if unseen:
            self.send(f"* OK [UNSEEN {unseen[0]}] First unseen\r\n")
        self.selected, self.readonly = True, readonly
        self.ok(tag, f"[{'READ-ONLY' if readonly else 'READ-WRITE'}] "
                     f"{'EXAMINE' if readonly else 'SELECT'} completed")

    async def cmd_SELECT(self, tag, args, uid):
        await self._select(tag, args, readonly=False)

    async def cmd_EXAMINE(self, tag, args, uid):
        await self._select(tag, args, readonly=True)

    async def cmd_LIST(self, tag, args, uid):
        self._require_auth()
        pattern = args[1] if len(args) > 1 else ""
        if pattern == "":
            self.send('* LIST (\\Noselect) "/" ""\r\n')
        elif pattern in ("*", "%") or str(pattern).upper() == "INBOX":
            self.send('* LIST (\\HasNoChildren) "/" "INBOX"\r\n')
        self.ok(tag, "LIST completed")

    cmd_LSUB = cmd_LIST

    async def cmd_STATUS(self, tag, args, uid):
        user = self._require_auth()
        self._inbox(args[0] if args else None)
        items = args[1] if len(args) > 1 and isinstance(args[1], list) else []
        messages = self.store.messages(user)
        box = self.store.status(user)
        values = {"MESSAGES": len(messages), "RECENT": 0, "UIDNEXT": box["uidnext"],
                  "UIDVALIDITY": box["uidvalidity"],
                  "UNSEEN": sum("\\Seen" not in m["flags"] for m in messages)}
        body = " ".join(f"{i.upper()} {values[i.upper()]}" for i in items
                        if i.upper() in values)
        self.send(f'* STATUS "INBOX" ({body})\r\n')
        self.ok(tag, "STATUS completed")

    async def cmd_CLOSE(self, tag, args, uid):
        user = self._require_selected()
        if not self.readonly:
            self.store.expunge(user)
        self.selected = False
        self.ok(tag, "CLOSE completed")

    async def cmd_UNSELECT(self, tag, args, uid):
        self._require_selected()
        self.selected = False
        self.ok(tag, "UNSELECT completed")

    async def cmd_EXPUNGE(self, tag, args, uid):
        user = self._require_selected()
        if self.readonly:
            raise IMAPError("Mailbox is read-only")
        for seq in self.store.expunge(user):
            self.send(f"* {seq} EXPUNGE\r\n")
        self.ok(tag, "EXPUNGE completed")

    # -- messages
    def _targets(self, spec: Any, uid: bool) -> list[tuple[int, dict]]:
        if not isinstance(spec, str):
            raise IMAPError("Missing message set", bad=True)
        messages = self.store.messages(self.user)
        numbered = list(enumerate(messages, start=1))
        if uid:
            wanted = resolve_set(spec, [m["uid"] for m in messages])
            return [(seq, m) for seq, m in numbered if m["uid"] in wanted]
        wanted = resolve_set(spec, [seq for seq, _ in numbered])
        return [(seq, m) for seq, m in numbered if seq in wanted]

    async def cmd_SEARCH(self, tag, args, uid):
        self._require_selected()
        messages = list(enumerate(self.store.messages(self.user), start=1))
        keys = list(args) or ["ALL"]
        matches = {seq for seq, _ in messages}
        i = 0
        while i < len(keys):
            key = keys[i].upper() if isinstance(keys[i], str) else ""
            i += 1
            if key == "ALL":
                continue
            flag_tests = {"SEEN": ("\\Seen", True), "UNSEEN": ("\\Seen", False),
                          "NEW": ("\\Seen", False), "OLD": ("\\Seen", True),
                          "DELETED": ("\\Deleted", True), "UNDELETED": ("\\Deleted", False),
                          "FLAGGED": ("\\Flagged", True), "UNFLAGGED": ("\\Flagged", False),
                          "ANSWERED": ("\\Answered", True),
                          "UNANSWERED": ("\\Answered", False)}
            if key in flag_tests:
                flag, present = flag_tests[key]
                matches &= {s for s, m in messages if (flag in m["flags"]) == present}
            elif key == "RECENT":
                matches = set()
            elif key in ("FROM", "TO", "SUBJECT") and i < len(keys):
                needle = str(keys[i]).lower().encode("utf-8")
                i += 1
                prefix = key.encode("ascii") + b":"
                matches &= {s for s, m in messages if any(
                    line.upper().startswith(prefix) and needle in line.lower()
                    for line in split_message(m["raw"])[0].splitlines())}
            elif key == "UID" and i < len(keys):
                wanted = resolve_set(str(keys[i]), [m["uid"] for _, m in messages])
                i += 1
                matches &= {s for s, m in messages if m["uid"] in wanted}
            elif key and (key[0].isdigit() or key[0] == "*"):
                matches &= resolve_set(key, [s for s, _ in messages])
            else:
                raise IMAPError(f"Unsupported SEARCH key {keys[i - 1]!r}", bad=True)
        found = [str(m["uid"] if uid else s) for s, m in messages if s in matches]
        self.send(f"* SEARCH{' ' if found else ''}{' '.join(found)}\r\n")
        self.ok(tag, "SEARCH completed")

    def _fetch_item(self, item: str, msg: dict, out: list[bytes]) -> bool:
        """Append one FETCH response item; return True when it sets ``\\Seen``."""
        upper = item.upper()
        raw = msg["raw"]
        header, text = split_message(raw)
        if upper == "UID":
            out.append(f"UID {msg['uid']}".encode())
        elif upper == "FLAGS":
            out.append(f"FLAGS ({' '.join(sorted(msg['flags']))})".encode())
        elif upper == "INTERNALDATE":
            out.append(f"INTERNALDATE {_internaldate(msg['internal_date'])}".encode())
        elif upper == "RFC822.SIZE":
            out.append(f"RFC822.SIZE {len(raw)}".encode())
        elif upper in ("RFC822", "RFC822.HEADER", "RFC822.TEXT"):
            data = {"RFC822": raw, "RFC822.HEADER": header, "RFC822.TEXT": text}[upper]
            out.append(f"{upper} {{{len(data)}}}\r\n".encode() + data)
            return upper != "RFC822.HEADER"
        elif upper.startswith(("BODY[", "BODY.PEEK[")):
            peek = upper.startswith("BODY.PEEK[")
            open_at, close_at = item.index("["), item.rindex("]")
            section = item[open_at + 1: close_at].strip()
            partial = _PARTIAL_RE.match(item[close_at + 1:]) if item[close_at + 1:] else None
            if item[close_at + 1:] and partial is None:
                raise IMAPError(f"Bad partial in {item!r}", bad=True)
            sec_upper = section.upper()
            if sec_upper == "":
                data = raw
            elif sec_upper == "HEADER":
                data = header
            elif sec_upper == "TEXT":
                data = text
            elif sec_upper.startswith(("HEADER.FIELDS ", "HEADER.FIELDS.NOT ")):
                names = tokenize(section.split(" ", 1)[1])
                if not names or not isinstance(names[0], list):
                    raise IMAPError("HEADER.FIELDS needs a list", bad=True)
                data = header_fields(header, {str(n).upper() for n in names[0]},
                                     exclude=sec_upper.startswith("HEADER.FIELDS.NOT"))
            else:
                raise IMAPError(f"Unsupported body section {section!r}", bad=True)
            label = f"BODY[{section}]"
            if partial:
                origin = int(partial.group(1))
                length = int(partial.group(2)) if partial.group(2) else len(data)
                data = data[origin: origin + length]
                label += f"<{origin}>"
            out.append(f"{label} {{{len(data)}}}\r\n".encode() + data)
            return not peek
        else:
            raise IMAPError(f"Unsupported FETCH item {item!r}", bad=True)
        return False

    async def cmd_FETCH(self, tag, args, uid):
        self._require_selected()
        if len(args) < 2:
            raise IMAPError("FETCH needs a set and items", bad=True)
        items = args[1] if isinstance(args[1], list) else args[1:]
        macros = {"ALL": ["FLAGS", "INTERNALDATE", "RFC822.SIZE"],
                  "FAST": ["FLAGS", "INTERNALDATE", "RFC822.SIZE"],
                  "FULL": ["FLAGS", "INTERNALDATE", "RFC822.SIZE"]}
        names: list[str] = []
        for item in items:
            if not isinstance(item, str):
                raise IMAPError("Malformed FETCH item list", bad=True)
            names.extend(macros.get(item.upper(), [item]))
        if uid and "UID" not in (n.upper() for n in names):
            names.insert(0, "UID")
        for seq, msg in self._targets(args[0], uid):
            parts: list[bytes] = []
            sets_seen = False
            for name in names:
                sets_seen |= self._fetch_item(name, msg, parts)
            if sets_seen and not self.readonly and "\\Seen" not in msg["flags"]:
                msg["flags"].add("\\Seen")
                self.store.set_flags(self.user, msg["uid"], msg["flags"])
                if "FLAGS" not in (n.upper() for n in names):
                    self._fetch_item("FLAGS", msg, parts)
            self.send(f"* {seq} FETCH (".encode() + b" ".join(parts) + b")\r\n")
        self.ok(tag, f"{'UID ' if uid else ''}FETCH completed")

    async def cmd_STORE(self, tag, args, uid):
        self._require_selected()
        if self.readonly:
            raise IMAPError("Mailbox is read-only")
        if len(args) < 3 or not isinstance(args[1], str):
            raise IMAPError("STORE needs a set, an operation and flags", bad=True)
        op = args[1].upper()
        silent = op.endswith(".SILENT")
        op = op.removesuffix(".SILENT")
        if op not in ("FLAGS", "+FLAGS", "-FLAGS"):
            raise IMAPError(f"Unsupported STORE operation {args[1]!r}", bad=True)
        raw_flags = args[2] if isinstance(args[2], list) else args[2:]
        flags = {f for f in raw_flags if isinstance(f, str)}
        canonical = {f.lower(): f for f in SYSTEM_FLAGS}
        flags = {canonical.get(f.lower(), f) for f in flags}
        for seq, msg in self._targets(args[0], uid):
            if op == "FLAGS":
                msg["flags"] = set(flags)
            elif op == "+FLAGS":
                msg["flags"] |= flags
            else:
                msg["flags"] -= flags
            self.store.set_flags(self.user, msg["uid"], msg["flags"])
            if not silent:
                uid_part = f"UID {msg['uid']} " if uid else ""
                self.send(f"* {seq} FETCH ({uid_part}FLAGS "
                          f"({' '.join(sorted(msg['flags']))}))\r\n")
        self.ok(tag, f"{'UID ' if uid else ''}STORE completed")


async def start_imap(config: MailConfig, store: MailStore, host: str, port: int):
    async def handle(reader, writer):
        try:
            await IMAPSession(config, store, reader, writer).run()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)
