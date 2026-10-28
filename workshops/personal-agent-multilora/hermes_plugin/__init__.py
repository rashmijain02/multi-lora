"""PersonaDesk Hermes plugin entry point.

Install with ``scripts/setup_hermes.py``, which links this directory into each persona profile's
``plugins/personadesk`` and enables it there (each Hermes profile has its own plugin folder). The
plugin registers five persona-scoped tools in
the ``personadesk`` toolset, a ``pre_tool_call`` guard, and the ``hermes personadesk``
operator command tree.
"""

from __future__ import annotations

import getpass
import logging
import os
from typing import Any

from .commands import CommandContext, dispatch, setup_parser
from .paths import workshop_root
from .store import open_store
from .tools import SCHEMAS, TOOLSET, Runtime, make_handlers, make_pre_tool_call

log = logging.getLogger(__name__)

SETTING_KEYS = (
    "workshop_root", "writer_backend", "writer_url", "writer_timeout_seconds", "classifier",
    "extra_allowed_tools", "hermes_bin",
)


def _settings(ctx: Any) -> dict[str, Any]:
    values = {}
    for key in SETTING_KEYS:
        value = ctx.get_config(key, default=None)
        if value is not None:
            values[key] = value
    return values


def register(ctx: Any) -> None:
    settings = _settings(ctx)
    root = workshop_root(settings.get("workshop_root"))

    def profile_name() -> str | None:
        return getattr(ctx, "profile_name", None)

    runtime = Runtime(root=root, settings=settings, profile_name=profile_name,
                      store_factory=open_store)
    handlers = make_handlers(runtime)
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handlers[name])
    ctx.register_hook("pre_tool_call", make_pre_tool_call(runtime))

    def handle_cli(args: Any) -> int:
        cc = CommandContext(
            root=root, profile=profile_name(), store_factory=open_store,
            principal=getpass.getuser(),
            hermes_bin=settings.get("hermes_bin") or os.environ.get("PERSONADESK_HERMES_BIN",
                                                                    "hermes"),
        )
        return dispatch(cc, args)

    ctx.register_cli_command(
        name="personadesk",
        help="PersonaDesk jobs, reviews, feedback, and releases",
        setup_fn=setup_parser,
        handler_fn=handle_cli,
    )
    log.info("personadesk: registered %d tools for profile %s", len(SCHEMAS), profile_name())
