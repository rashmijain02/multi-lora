"""``pd-mail``: run the local mail simulator and send/read mail between local accounts.

Examples (from the workshop directory)::

    uv run pd-mail serve                      # SMTP 127.0.0.1:2525, IMAP 127.0.0.1:1143
    uv run pd-mail accounts
    uv run pd-mail seed --persona priya-raman-support
    uv run pd-mail send --from alex.morgan@customer.example \\
        --to priya.raman@company.example --subject "Hi" --body "Export fails again"
    uv run pd-mail inbox --user priya.raman@company.example
    uv run pd-mail read --user priya.raman@company.example 1
"""

from __future__ import annotations

import argparse
import asyncio
import imaplib
import json
import sys
import time
from pathlib import Path

import requests

from hermes_plugin.paths import artifacts_dir, safe_child, workshop_root

from .client import body_text, list_inbox, read_message, send_mail
from .config import load_config
from .jmap import JmapServer
from .jmap_client import JmapClient, JmapError
from .jmap_seed import PERSONAS, build_all, manifest
from .jmap_seed import seed as jmap_import
from .jmapstore import JmapStore
from .server import MailServer
from .store import MailStore

FIXTURE_HEADER = "X-PersonaDesk-Fixture"


def default_db(root: Path) -> Path:
    return artifacts_dir(root) / "mail" / "mail.db"


def default_jmap_db(root: Path) -> Path:
    return artifacts_dir(root) / "mail" / "jmap.db"


def seed(config, root: Path, persona: str | None = None, port: int | None = None) -> list[dict]:
    """Send every persona fixture as a real email from its fixture sender."""
    sent = []
    for fixture_path in sorted((root / "fixtures").glob("*/*.json")):
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        client_id = fixture["client_id"]
        if persona and client_id != persona:
            continue
        to = config.persona_account(client_id).address
        message_id = send_mail(config, fixture["from"], [to], fixture["subject"],
                               fixture["body"], headers={FIXTURE_HEADER: fixture["id"]},
                               port=port)
        sent.append({"fixture": fixture["id"], "from": fixture["from"], "to": to,
                     "message_id": message_id})
    return sent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pd-mail", description=__doc__.split("\n\n")[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", help="Workshop root (default: auto-detect)")
    parser.add_argument("--db", help="Store path (default: artifacts/mail/mail.db for SMTP/IMAP,"
                        " artifacts/mail/jmap.db for JMAP)")
    subs = parser.add_subparsers(dest="command", required=True)

    serve = subs.add_parser("serve", help="Run SMTP + IMAP on loopback until Ctrl+C")
    serve.add_argument("--smtp-port", type=int)
    serve.add_argument("--imap-port", type=int)

    subs.add_parser("accounts", help="List local addresses and the shared lab password")

    send = subs.add_parser("send", help="Send a message between local accounts")
    send.add_argument("--from", dest="sender", required=True)
    send.add_argument("--to", required=True, action="append", help="Repeat for more recipients")
    send.add_argument("--subject", required=True)
    body = send.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--body-file", help="Workshop-relative text file")
    send.add_argument("--in-reply-to", help="Message-ID being answered")

    inbox = subs.add_parser("inbox", help="List an account's INBOX")
    inbox.add_argument("--user", required=True)
    inbox.add_argument("--unseen", action="store_true")

    read = subs.add_parser("read", help="Print one message")
    read.add_argument("--user", required=True)
    read.add_argument("uid", type=int)
    read.add_argument("--peek", action="store_true", help="Do not mark the message seen")

    seed_p = subs.add_parser("seed", help="Send the persona fixtures as emails")
    seed_p.add_argument("--persona", help="Only this persona's fixtures")

    subs.add_parser("reset", help="Delete every stored message")

    jserve = subs.add_parser("jmap-serve", help="Run the JMAP playground on loopback")
    jserve.add_argument("--port", type=int, help="Default: jmap_port in config/mailboxes.json")

    jseed = subs.add_parser("jmap-seed", help="Import the synthetic mailbox pack over JMAP")
    jseed.add_argument("--persona", help="Only this persona (default: all three)")
    jseed.add_argument("--port", type=int)
    jseed.add_argument("--manifest", action="store_true",
                       help="Print the fixture manifest and exit (no server needed)")

    subs.add_parser("jmap-reset", help="Empty every JMAP mailbox (the JMAP store only)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = workshop_root(args.root)
    config = load_config(root)
    db = Path(args.db) if args.db else default_db(root)
    jmap_db = Path(args.db) if args.db else default_jmap_db(root)

    def emit(payload) -> None:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))

    try:
        if args.command == "serve":
            server = MailServer(config, db, smtp_port=args.smtp_port, imap_port=args.imap_port)
            print(f"mailsim: SMTP {server.host}:{server.smtp_port}  IMAP "
                  f"{server.host}:{server.imap_port}  (local accounts only; Ctrl+C to stop)",
                  flush=True)
            try:
                asyncio.run(server.serve())
            except KeyboardInterrupt:
                pass
            return 0
        if args.command == "accounts":
            emit({"smtp": f"{config.host}:{config.smtp_port}",
                  "imap": f"{config.host}:{config.imap_port}",
                  "password": config.password,
                  "accounts": [{"address": a.address, "name": a.name, "persona": a.persona}
                               for a in config.accounts.values()]})
        elif args.command == "send":
            text = args.body if args.body is not None else safe_child(
                root, *Path(args.body_file).parts).read_text(encoding="utf-8")
            emit({"ok": True, "message_id": send_mail(
                config, args.sender, args.to, args.subject, text,
                in_reply_to=args.in_reply_to)})
        elif args.command == "inbox":
            emit(list_inbox(config, args.user, unseen=args.unseen))
        elif args.command == "read":
            msg = read_message(config, args.user, args.uid, mark_seen=not args.peek)
            emit({name: str(msg[name]) for name in (
                "From", "To", "Subject", "Date", "Message-ID", "In-Reply-To",
                "Authentication-Results", FIXTURE_HEADER) if msg[name] is not None}
                 | {"body": body_text(msg)})
        elif args.command == "seed":
            emit(seed(config, root, args.persona))
        elif args.command == "reset":
            store = MailStore(db)
            store.reset()
            store.close()
            emit({"ok": True, "reset": "all mailboxes emptied"})
        elif args.command == "jmap-serve":
            jmap = JmapServer(config, jmap_db, port=args.port).start()
            print(f"mailsim: JMAP {jmap.base_url}  (loopback only, no sending; Ctrl+C to stop)",
                  flush=True)
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
            finally:
                jmap.stop()
        elif args.command == "jmap-seed":
            packs = build_all()
            if args.persona and args.persona not in packs:
                raise KeyError(f"Unknown persona {args.persona!r}; choose from {sorted(packs)}.")
            if args.manifest:
                emit(manifest({p: v for p, v in packs.items()
                               if not args.persona or p == args.persona}))
                return 0
            base = f"http://{config.host}:{args.port or config.jmap_port}"
            results = {}
            for persona, pack in packs.items():
                if args.persona and persona != args.persona:
                    continue
                report = jmap_import(
                    JmapClient(base, PERSONAS[persona]["address"], config.password), pack)
                results[persona] = {"imported": report.imported, "already_present": report.present,
                                    "failed": report.failed, "ok": report.ok}
            emit(results)
            return 0 if all(r["ok"] for r in results.values()) else 1
        elif args.command == "jmap-reset":
            store = JmapStore(jmap_db)
            store.reset()
            store.close()
            emit({"ok": True, "reset": "all JMAP mailboxes emptied"})
        return 0
    except (OSError, ValueError, KeyError, JmapError, imaplib.IMAP4.error) as exc:
        refused = isinstance(exc, ConnectionRefusedError | requests.ConnectionError)
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc),
              "hint": "Is `pd-mail serve` / `pd-mail jmap-serve` running?" if refused else None})
        return 2


if __name__ == "__main__":
    sys.exit(main())
