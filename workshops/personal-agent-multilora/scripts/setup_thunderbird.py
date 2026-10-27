"""Create a Thunderbird profile wired to every local mailsim account.

Run from the workshop directory (``workshops/personal-agent-multilora``) with Thunderbird
closed::

    uv run python scripts/setup_thunderbird.py              # print the plan only
    uv run python scripts/setup_thunderbird.py --apply      # create the profile

The profile is separate from any personal Thunderbird profile. Accounts use plaintext IMAP and
SMTP on loopback, read from ``config/mailboxes.json``. mailsim has only an INBOX, so Sent,
Drafts and Templates live in Thunderbird's Local Folders, and deleting a message removes it
immediately instead of moving it to a server Trash folder. Passwords are not written: enter the
shared lab password once per account and let Thunderbird remember it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

WORKSHOP = Path(__file__).resolve().parents[1]
PROFILE_NAME = "personadesk"
LOCAL_FOLDERS = "mailbox://nobody@Local%20Folders"


def default_profile_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ["APPDATA"]) / "Thunderbird"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Thunderbird"
    else:
        base = Path.home() / ".thunderbird"
    return base / "Profiles" / "personadesk-mailsim"


def find_thunderbird() -> str | None:
    found = shutil.which("thunderbird")
    if found:
        return found
    candidates = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]) / "Mozilla Thunderbird" / "thunderbird.exe")
    candidates.append(Path("/Applications/Thunderbird.app/Contents/MacOS/thunderbird"))
    return next((str(c) for c in candidates if c.is_file()), None)


def build_prefs(mailboxes: dict, addresses: list[str] | None = None) -> dict[str, object]:
    """Return Thunderbird prefs for ``addresses`` (default: every mailsim account)."""
    server = mailboxes["server"]
    addresses = addresses or list(mailboxes["accounts"])
    unknown = [a for a in addresses if a not in mailboxes["accounts"]]
    if unknown:
        raise ValueError(f"not mailsim accounts: {', '.join(unknown)}")
    prefs: dict[str, object] = {
        "mail.shell.checkDefaultClient": False,
        "mailnews.start_page.enabled": False,
        "mail.provider.enabled": False,
        "mail.imap.mime_parts_on_demand": False,
        "datareporting.policy.dataSubmissionEnabled": False,
        "mail.server.server1.type": "none",
        "mail.server.server1.hostname": "Local Folders",
        "mail.server.server1.userName": "nobody",
        "mail.server.server1.name": "Local Folders",
        "mail.server.server1.directory-rel": "[ProfD]Mail/Local Folders",
        "mail.account.account1.server": "server1",
        "mail.accountmanager.localfoldersserver": "server1",
    }
    accounts, smtps = [], []
    for n, address in enumerate(addresses, start=2):
        name = mailboxes["accounts"][address]["name"]
        srv, ident, acct, smtp = f"server{n}", f"id{n}", f"account{n}", f"smtp{n}"
        accounts.append(acct)
        smtps.append(smtp)
        prefs.update({
            f"mail.account.{acct}.server": srv,
            f"mail.account.{acct}.identities": ident,
            f"mail.server.{srv}.type": "imap",
            f"mail.server.{srv}.hostname": server["host"],
            f"mail.server.{srv}.port": server["imap_port"],
            f"mail.server.{srv}.userName": address,
            f"mail.server.{srv}.name": f"{name} (mailsim)",
            f"mail.server.{srv}.socketType": 0,
            f"mail.server.{srv}.authMethod": 3,
            f"mail.server.{srv}.login_at_startup": True,
            f"mail.server.{srv}.check_new_mail": True,
            f"mail.server.{srv}.check_time": 1,
            f"mail.server.{srv}.delete_model": 2,
            f"mail.server.{srv}.use_idle": False,
            f"mail.server.{srv}.directory-rel": f"[ProfD]ImapMail/{address}",
            f"mail.identity.{ident}.fullName": name,
            f"mail.identity.{ident}.useremail": address,
            f"mail.identity.{ident}.valid": True,
            f"mail.identity.{ident}.smtpServer": smtp,
            f"mail.identity.{ident}.fcc": True,
            f"mail.identity.{ident}.fcc_folder": f"{LOCAL_FOLDERS}/Sent",
            f"mail.identity.{ident}.fcc_folder_picker_mode": "1",
            f"mail.identity.{ident}.draft_folder": f"{LOCAL_FOLDERS}/Drafts",
            f"mail.identity.{ident}.drafts_folder_picker_mode": "1",
            f"mail.identity.{ident}.stationery_folder": f"{LOCAL_FOLDERS}/Templates",
            f"mail.identity.{ident}.tmpl_folder_picker_mode": "1",
            f"mail.identity.{ident}.archive_enabled": False,
            f"mail.smtpserver.{smtp}.hostname": server["host"],
            f"mail.smtpserver.{smtp}.port": server["smtp_port"],
            f"mail.smtpserver.{smtp}.username": address,
            f"mail.smtpserver.{smtp}.description": f"mailsim {name}",
            f"mail.smtpserver.{smtp}.try_ssl": 0,
            f"mail.smtpserver.{smtp}.authMethod": 3,
        })
    prefs["mail.accountmanager.accounts"] = ",".join([*accounts, "account1"])
    prefs["mail.accountmanager.defaultaccount"] = accounts[0]
    prefs["mail.account.lastKey"] = len(addresses) + 1
    prefs["mail.smtpservers"] = ",".join(smtps)
    prefs["mail.smtp.defaultserver"] = smtps[0]
    return prefs


def render_prefs(prefs: dict[str, object]) -> str:
    lines = ["// PersonaDesk mailsim profile, generated by scripts/setup_thunderbird.py."]
    lines += [f"user_pref({json.dumps(k)}, {json.dumps(v)});" for k, v in prefs.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--apply", action="store_true", help="Create the profile")
    parser.add_argument("--profile-dir", type=Path, default=None,
                        help="Profile folder (default: Thunderbird's Profiles/personadesk-mailsim)")
    parser.add_argument("--account", action="append", dest="accounts",
                        help="Only this address; repeat for more (default: all accounts)")
    parser.add_argument("--thunderbird", help="Path to the Thunderbird executable")
    parser.add_argument("--force", action="store_true",
                        help="Replace the prefs of an existing profile (Thunderbird must be closed)")
    args = parser.parse_args(argv)

    mailboxes = json.loads((WORKSHOP / "config" / "mailboxes.json").read_text(encoding="utf-8"))
    prefs = build_prefs(mailboxes, args.accounts)
    profile = (args.profile_dir or default_profile_dir()).expanduser().resolve()
    prefs_file = profile / "prefs.js"
    exe = args.thunderbird or find_thunderbird()
    if exe and not (Path(exe).is_file() or shutil.which(exe)):
        exe = None
    accounts = args.accounts or list(mailboxes["accounts"])

    print(f"Thunderbird: {exe or 'not found (install it, or pass --thunderbird)'}")
    print(f"Profile:     {profile}")
    print(f"Accounts:    {len(accounts)} ({', '.join(accounts)})")
    if prefs_file.exists() and not args.force:
        print("prefs.js already exists; pass --force to replace it (close Thunderbird first).")
        return 1
    if not args.apply:
        print("Plan only. Re-run with --apply to create the profile.")
        return 0

    if exe and not profile.exists():
        # Registers the profile in profiles.ini so the profile manager lists it.
        subprocess.run([exe, "-CreateProfile", f"{PROFILE_NAME} {profile}"], check=False)
    profile.mkdir(parents=True, exist_ok=True)
    prefs_file.write_text(render_prefs(prefs), encoding="utf-8")
    print(f"Wrote {prefs_file}")
    print(f"Lab password: {mailboxes['server']['shared_password']} "
          "(enter once per account; tick 'Use Password Manager to remember')")
    print(f'Start with: "{exe or "thunderbird"}" -profile "{profile}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
