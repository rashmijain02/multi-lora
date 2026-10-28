"""Run the SMTP and IMAP listeners together, in the foreground or in a background thread."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from .config import MailConfig
from .imap import start_imap
from .smtp import start_smtp
from .store import MailStore


class MailServer:
    """Both listeners on one event loop. Port 0 picks a free port (used by tests)."""

    def __init__(self, config: MailConfig, db_path: Path, host: str | None = None,
                 smtp_port: int | None = None, imap_port: int | None = None):
        self.config = config
        self.db_path = db_path
        self.host = host or config.host
        self.smtp_port = config.smtp_port if smtp_port is None else smtp_port
        self.imap_port = config.imap_port if imap_port is None else imap_port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stopped: asyncio.Event | None = None

    async def serve(self, ready: threading.Event | None = None) -> None:
        store = MailStore(self.db_path)
        smtp = await start_smtp(self.config, store, self.host, self.smtp_port)
        imap = await start_imap(self.config, store, self.host, self.imap_port)
        self.smtp_port = smtp.sockets[0].getsockname()[1]
        self.imap_port = imap.sockets[0].getsockname()[1]
        self._stopped = asyncio.Event()
        if ready:
            ready.set()
        try:
            await self._stopped.wait()
        finally:
            for server in (smtp, imap):
                server.close()
                await server.wait_closed()
            store.close()

    def start(self) -> MailServer:
        ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_until_complete, args=(self.serve(ready),), daemon=True)
        self._thread.start()
        if not ready.wait(10):
            raise RuntimeError("mailsim did not start")
        return self

    def stop(self) -> None:
        if self._loop and self._stopped:
            self._loop.call_soon_threadsafe(self._stopped.set)
        if self._thread:
            self._thread.join(10)
        if self._loop and not self._loop.is_running():
            self._loop.close()
