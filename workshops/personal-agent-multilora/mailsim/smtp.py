"""Minimal SMTP submission server that delivers only to configured local mailboxes.

Supported: EHLO/HELO, AUTH PLAIN/LOGIN, MAIL, RCPT, DATA, RSET, NOOP, QUIT.
Authentication is optional; an authenticated sender whose login matches ``From:`` gets a
``dmarc=pass`` Authentication-Results stamp, anything else gets ``dmarc=fail``.
"""

from __future__ import annotations

import asyncio
import base64
import email.utils
import re
import time
from email import policy
from email.parser import BytesParser

from .config import MailConfig
from .store import MailStore

MAX_MESSAGE_BYTES = 10 * 1024 * 1024
_PATH_RE = re.compile(r"^(?:FROM|TO):\s*<([^>]*)>", re.IGNORECASE)


def _b64(text: str) -> str:
    try:
        return base64.b64decode(text, validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def stamp(raw: bytes, config: MailConfig, auth_user: str | None, recipient: str) -> bytes:
    """Strip sender-written Authentication-Results and prepend our own (RFC 8601)."""
    msg = BytesParser(policy=policy.SMTP).parsebytes(raw)
    del msg["Authentication-Results"]
    if msg["Message-ID"] is None:
        msg["Message-ID"] = email.utils.make_msgid(domain="mailsim.local")
    if msg["Date"] is None:
        msg["Date"] = email.utils.formatdate(localtime=False)
    from_addr = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    domain = from_addr.rpartition("@")[2] or "unknown"
    verdict = "pass" if auth_user and auth_user == from_addr else "fail"
    header = (f"Authentication-Results: {config.authserv_id}; dmarc={verdict} "
              f"header.from={domain}\r\n"
              f"Received: from localhost by {config.authserv_id} for <{recipient}>; "
              f"{email.utils.formatdate(time.time())}\r\n")
    return header.encode("ascii") + msg.as_bytes()


class SMTPSession:
    def __init__(self, config: MailConfig, store: MailStore, reader, writer):
        self.config, self.store, self.reader, self.writer = config, store, reader, writer
        self.auth_user: str | None = None
        self._reset()

    def _reset(self) -> None:
        self.mail_from: str | None = None
        self.rcpts: list[str] = []

    async def reply(self, line: str) -> None:
        self.writer.write(line.encode("utf-8") + b"\r\n")
        await self.writer.drain()

    async def readline(self) -> str | None:
        line = await self.reader.readline()
        return None if not line else line.decode("utf-8", "replace").rstrip("\r\n")

    async def run(self) -> None:
        await self.reply(f"220 {self.config.authserv_id} PersonaDesk mailsim ESMTP (local only)")
        while (line := await self.readline()) is not None:
            verb, _, arg = line.partition(" ")
            handler = getattr(self, f"cmd_{verb.upper()}", None)
            if handler is None:
                await self.reply("502 Command not implemented")
                continue
            if await handler(arg.strip()) is False:
                break

    async def cmd_EHLO(self, arg: str) -> None:
        self._reset()
        self.writer.write(f"250-{self.config.authserv_id} hello\r\n250-8BITMIME\r\n"
                          "250 AUTH PLAIN LOGIN\r\n".encode())
        await self.writer.drain()

    async def cmd_HELO(self, arg: str) -> None:
        self._reset()
        await self.reply(f"250 {self.config.authserv_id}")

    async def cmd_AUTH(self, arg: str) -> None:
        mech, _, initial = arg.partition(" ")
        mech = mech.upper()
        if mech == "PLAIN":
            if not initial:
                await self.reply("334 ")
                initial = await self.readline() or ""
            parts = _b64(initial).split("\x00")
            user, password = (parts[1], parts[2]) if len(parts) == 3 else ("", "")
        elif mech == "LOGIN":
            if initial:
                user = _b64(initial)
            else:
                await self.reply("334 VXNlcm5hbWU6")
                user = _b64(await self.readline() or "")
            await self.reply("334 UGFzc3dvcmQ6")
            password = _b64(await self.readline() or "")
        else:
            await self.reply("504 Unsupported authentication mechanism")
            return
        address = self.config.check_login(user, password)
        if address is None:
            await self.reply("535 Authentication failed")
            return
        self.auth_user = address
        await self.reply("235 Authentication succeeded")

    async def cmd_MAIL(self, arg: str) -> None:
        match = _PATH_RE.match(arg)
        if not match:
            await self.reply("501 Syntax: MAIL FROM:<address>")
            return
        sender = match.group(1).lower()
        if self.config.account(sender) is None:
            await self.reply("550 Sender is not a local mailsim account")
            return
        self._reset()
        self.mail_from = sender
        await self.reply("250 OK")

    async def cmd_RCPT(self, arg: str) -> None:
        if self.mail_from is None:
            await self.reply("503 MAIL first")
            return
        match = _PATH_RE.match(arg)
        if not match:
            await self.reply("501 Syntax: RCPT TO:<address>")
            return
        account = self.config.account(match.group(1))
        if account is None:
            await self.reply("550 No such local mailbox (mailsim never relays)")
            return
        self.rcpts.append(account.address)
        await self.reply("250 OK")

    async def cmd_DATA(self, arg: str) -> None:
        if not self.rcpts:
            await self.reply("503 RCPT first")
            return
        await self.reply("354 End data with <CR><LF>.<CR><LF>")
        chunks: list[bytes] = []
        size = 0
        while True:
            line = await self.reader.readline()
            if not line:
                return
            if line in (b".\r\n", b".\n"):
                break
            if line.startswith(b".."):
                line = line[1:]
            size += len(line)
            if size <= MAX_MESSAGE_BYTES:
                chunks.append(line)
        if size > MAX_MESSAGE_BYTES:
            await self.reply("552 Message too large")
        else:
            raw = b"".join(chunks)
            for rcpt in self.rcpts:
                self.store.deliver(rcpt, stamp(raw, self.config, self.auth_user, rcpt))
            await self.reply(f"250 OK delivered to {len(self.rcpts)} local mailbox(es)")
        self._reset()

    async def cmd_RSET(self, arg: str) -> None:
        self._reset()
        await self.reply("250 OK")

    async def cmd_NOOP(self, arg: str) -> None:
        await self.reply("250 OK")

    async def cmd_QUIT(self, arg: str) -> bool:
        await self.reply("221 Bye")
        return False


async def start_smtp(config: MailConfig, store: MailStore, host: str, port: int):
    async def handle(reader, writer):
        try:
            await SMTPSession(config, store, reader, writer).run()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)
