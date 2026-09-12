"""morrowfriends:// join links so friends never paste an mf2 token."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .invite import Invite, parse_invite

SCHEME = "morrowfriends"


def invite_to_deeplink(invite: Invite) -> str:
    return f"{SCHEME}://join/{invite.to_token()}"


def parse_deeplink(text: str) -> Invite | None:
    """Return an Invite from a deeplink, raw token, or host:port string."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.lower().startswith(f"{SCHEME}:"):
        parsed = urlparse(raw)
        path = unquote(parsed.path or "").strip("/")
        query = parse_qs(parsed.query)
        token = ""
        if parsed.netloc.lower() == "join":
            token = path.split("/", 1)[0] if path else ""
        elif path.lower().startswith("join/"):
            token = path.split("/", 1)[1]
        elif path.lower() == "join":
            token = ""
        if not token:
            values = query.get("invite") or query.get("token") or []
            token = values[0] if values else ""
        if not token:
            raise ValueError("That MorrowFriends link is missing a party invite.")
        return parse_invite(token)
    return parse_invite(raw)


def consume_startup_invite(argv: list[str] | None = None) -> Invite | None:
    """Read the first morrowfriends:// or mf2. argument from process argv."""
    values = list(sys.argv[1:] if argv is None else argv)
    for value in values:
        text = value.strip()
        if not text:
            continue
        if text.lower().startswith(f"{SCHEME}:") or text.startswith(("mf1.", "mf2.")):
            return parse_deeplink(text)
    return None


def register_protocol() -> bool:
    """Register a per-user Windows protocol handler for morrowfriends://."""
    if os.name != "nt":
        return False
    try:
        import winreg
    except ImportError:
        return False
    if getattr(sys, "frozen", False):
        command = f'"{sys.executable}" "%1"'
    else:
        run_py = str((Path(__file__).resolve().parents[1] / "run.py").resolve())
        command = f'"{sys.executable}" "{run_py}" "%1"'
    try:
        classes = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\morrowfriends")
        with classes:
            winreg.SetValueEx(classes, None, 0, winreg.REG_SZ, "URL:MorrowFriends Party")
            winreg.SetValueEx(classes, "URL Protocol", 0, winreg.REG_SZ, "")
            command_key = winreg.CreateKey(classes, r"shell\open\command")
            with command_key:
                winreg.SetValueEx(command_key, None, 0, winreg.REG_SZ, command)
        return True
    except OSError:
        return False
