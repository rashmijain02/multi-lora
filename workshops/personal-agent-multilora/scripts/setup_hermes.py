"""Wire PersonaDesk into a local Hermes install: plugin link, persona profiles, settings.

Run from the workshop directory (``workshops/personal-agent-multilora``)::

    uv run python scripts/setup_hermes.py                 # print the plan only
    uv run python scripts/setup_hermes.py --apply         # make the changes
    uv run python scripts/setup_hermes.py --apply --writer http \
        --model Qwen/Qwen3-8B --base-url http://127.0.0.1:8000/v1
    uv run python scripts/setup_hermes.py --apply --provider copilot --model claude-sonnet-4.5

Every change goes through Hermes's own CLI (``hermes profile create``, ``hermes config set``,
``hermes plugins enable``) except two file operations Hermes has no command for: linking the
plugin folder and installing each profile's ``SOUL.md``. Persona profiles are created empty
(``--no-skills``) and never cloned, so the default profile's memories and secrets stay out.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

WORKSHOP = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = WORKSHOP / "hermes_plugin"

# Self-improvement stays human-gated: staged memory/skill writes, no autonomous curator or
# background review (PROPOSAL.md section 4).
GOVERNANCE = {
    "memory.write_approval": "true",
    "skills.write_approval": "true",
    "curator.enabled": "false",
    "auxiliary.background_review.enabled": "false",
}


class Planner:
    def __init__(self, hermes: str, apply: bool):
        self.hermes, self.apply = hermes, apply

    def run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run([self.hermes, *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=check)

    def change(self, description: str, *args: str) -> None:
        print(("  run  " if self.apply else "  plan ") + description)
        if self.apply:
            result = self.run(*args, check=False)
            if result.returncode != 0:
                sys.exit(f"hermes {' '.join(args)} failed:\n{result.stdout}{result.stderr}")


def hermes_home(planner: Planner) -> Path:
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]).expanduser()
    return Path(planner.run("config", "path").stdout.strip()).parent


def profile_dir(planner: Planner, profile: str) -> Path | None:
    result = planner.run("-p", profile, "config", "path", check=False)
    path = result.stdout.strip()
    return Path(path).parent if result.returncode == 0 and path else None


def link_plugin(home: Path, apply: bool) -> None:
    """Link the plugin into one Hermes home; every profile has its own ``plugins/`` folder."""
    target = home / "plugins" / "personadesk"
    if target.exists() or target.is_symlink():
        is_link = target.is_symlink() or bool(getattr(target, "is_junction", lambda: False)())
        if not is_link:
            sys.exit(f"Refusing to replace {target}: it is not a link. Remove it yourself.")
        if target.resolve() == PLUGIN_SOURCE.resolve():
            print(f"  ok   plugin link {target}")
            return
    print(("  run  " if apply else "  plan ") + f"link {target} -> {PLUGIN_SOURCE}")
    if not apply:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        os.unlink(target) if target.is_symlink() else os.rmdir(target)
    if os.name == "nt":  # a junction needs no administrator rights
        subprocess.run(["cmd", "/c", "mklink", "/J", str(target), str(PLUGIN_SOURCE)],
                       check=True, capture_output=True)
    else:
        target.symlink_to(PLUGIN_SOURCE, target_is_directory=True)


def install_soul(planner: Planner, profile: str) -> None:
    source = WORKSHOP / "profiles" / profile / "SOUL.md"
    directory = profile_dir(planner, profile)
    if directory is None:
        print(f"  plan copy {source.name} into the new {profile} profile")
        return
    target = directory / "SOUL.md"
    if target.is_file() and filecmp.cmp(source, target, shallow=False):
        print(f"  ok   {profile} SOUL.md")
        return
    print(("  run  " if planner.apply else "  plan ") + f"install {profile} SOUL.md")
    if planner.apply:
        if target.is_file():
            shutil.copy2(target, target.with_suffix(".md.bak"))
        shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="make changes (default: plan)")
    parser.add_argument("--hermes-bin", default=os.environ.get("PERSONADESK_HERMES_BIN",
                                                               "hermes"))
    parser.add_argument("--writer", choices=("template", "http"), default="template",
                        help="template = E0 baseline; http = scripts/writer_service.py")
    parser.add_argument("--writer-url", default="http://127.0.0.1:8100")
    parser.add_argument("--model", help="controller model id")
    parser.add_argument("--provider", default="custom",
                        help="Hermes provider for --model (default: custom, needs --base-url; "
                             "e.g. copilot uses Hermes's stored credential instead)")
    parser.add_argument("--base-url", help="e.g. http://127.0.0.1:8000/v1 (vLLM or llama.cpp)")
    args = parser.parse_args()
    if args.base_url and not args.model:
        parser.error("--base-url needs --model")
    if args.model and (args.provider == "custom") != bool(args.base_url):
        parser.error("--base-url is required with provider custom and only valid with it")

    hermes = shutil.which(args.hermes_bin)
    if not hermes:
        sys.exit(f"Hermes executable '{args.hermes_bin}' not found on PATH.")
    planner = Planner(hermes, args.apply)
    home = hermes_home(planner)
    print(f"Hermes home: {home}\nWorkshop:    {WORKSHOP}\n")

    permissions = json.loads((WORKSHOP / "config" / "persona_permissions.json").read_text(
        encoding="utf-8"))
    settings = {
        "workshop_root": str(WORKSHOP),
        "writer_backend": args.writer,
        **({"writer_url": args.writer_url} if args.writer == "http" else {}),
    }
    for client_id, grant in permissions["personas"].items():
        if not grant["enabled"]:
            continue
        profile = grant["hermes_profile"]
        print(f"\n[{profile}] {client_id}")
        if profile_dir(planner, profile) is None:
            planner.change(f"create profile {profile}", "profile", "create", profile,
                           "--no-skills", "--no-alias",
                           "--description", f"PersonaDesk controller for {client_id}")
        for key, value in settings.items():
            planner.change(f"set plugin setting {key}", "-p", profile, "config", "set",
                           f"plugins.entries.personadesk.settings.{key}", value)
        for key, value in GOVERNANCE.items():
            planner.change(f"set {key}={value}", "-p", profile, "config", "set", key, value)
        if args.model:
            model_keys = [("model.provider", args.provider), ("model.default", args.model)]
            if args.base_url:
                model_keys.append(("model.base_url", args.base_url))
            for key, value in model_keys:
                planner.change(f"set {key}", "-p", profile, "config", "set", key, value)
        install_soul(planner, profile)
        directory = profile_dir(planner, profile)
        if directory is None:
            print(f"  plan link plugin into the new {profile} profile")
        else:
            link_plugin(directory, args.apply)
        planner.change("enable plugin personadesk", "-p", profile, "plugins", "enable",
                       "personadesk")

    print("\nNext:" if args.apply else "\nRe-run with --apply to make these changes. Then:")
    if not args.model:
        print("  hermes -p pd-priya model            # choose each profile's controller model")
    print("  hermes -p pd-priya plugins doctor personadesk")
    print("  hermes -p pd-priya personadesk run --fixture priya-001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
