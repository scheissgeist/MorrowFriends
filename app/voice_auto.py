"""Attach proximity voice without typing /voice or pasting a code."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import openmw_user_config_dir, read_voice_claims
from .paths import tes3mp_dir
from .preferences import load_ptt_binding
from .ptt_binding import normalize_ptt_binding, ptt_wire_value
from .voice_client import friend_voice_url, open_voice_client

CLAIM_IN_LOG = re.compile(r"Voice setup code:\s*([A-Z0-9]{16})", re.IGNORECASE)
# This client's own TES3MP greeting. Chat lines are `#FFFFFFName (pid): …`.
# Other people joining write `Name (n) has joined the server` — do not use
# those. Guessing from /health is how a visitor claimed the host.
_WELCOME_LINE = re.compile(r"\] \[INFO\]: Welcome (.+)$")
_LOGIN_TIMER = re.compile(r"^You have \d+ seconds to (?:register|log in)\.\s*$")


def parse_local_login_name(text: str) -> str | None:
    """Return this client's TES3MP account name from its own log text."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _WELCOME_LINE.search(line)
        if match is None:
            continue
        name = match.group(1).strip()
        if not name or "#" in name or len(name) > 64:
            continue
        for follow in lines[index + 1 : index + 4]:
            stripped = follow.strip()
            if not stripped:
                continue
            if _LOGIN_TIMER.match(stripped):
                return name
            break
    return None


def tes3mp_client_log_dir(directory: Path | None = None) -> Path:
    return directory if directory is not None else openmw_user_config_dir()


def local_login_name(*, since: float, directory: Path | None = None) -> str | None:
    """Account name this TES3MP process logged in as, or None until it does.

    Only logs written after `since` (unix mtime) are read, so a leftover
    session on this PC cannot supply someone else's name.
    """
    root = tes3mp_client_log_dir(directory)
    if not root.is_dir():
        return None
    found: tuple[float, str] | None = None
    for path in root.glob("tes3mp-client-*.log"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime < since - 5:
            continue
        try:
            text = path.read_bytes()[: 256 * 1024].decode("utf-8", errors="replace")
        except OSError:
            continue
        name = parse_local_login_name(text)
        if name and (found is None or mtime >= found[0]):
            found = (mtime, name)
    return found[1] if found else None


def pending_claim_code(player_name: str, tes3mp_root: Path | None = None) -> str | None:
    """Return the unused host-side claim code for a connected character, if any."""
    if not player_name:
        return None
    payload = read_voice_claims(tes3mp_root or tes3mp_dir())
    claims = payload.get("claims", {})
    if not isinstance(claims, dict):
        return None
    wanted = player_name.casefold()
    for code, claim in claims.items():
        if not isinstance(code, str) or not isinstance(claim, dict):
            continue
        if str(claim.get("player", "")).casefold() == wanted:
            return code.strip().upper()
    return None


def scan_tes3mp_logs_for_claim(root: Path | None = None) -> str | None:
    """Read a locally logged /voice-style code after TES3MP prints it."""
    base = root or tes3mp_dir()
    candidates = [
        base / "tes3mp.log",
        base / "tes3mp-client.log",
        base / "server" / "tes3mp-server.log",
    ]
    newest: tuple[float, str] | None = None
    for path in candidates:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            matches = CLAIM_IN_LOG.findall(text)
            if not matches:
                continue
            newest = (path.stat().st_mtime, matches[-1].upper())
        except OSError:
            continue
    return newest[1] if newest else None


def auto_claim_credentials(party_id: str, player_name: str, page_url: str) -> dict | None:
    """Ask the public relay to bind this connected character without a typed code."""
    if not party_id or not player_name:
        return None
    parsed_root = page_url.rstrip("/")
    request = Request(
        f"{parsed_root}/v1/auto-claim",
        data=json.dumps({"party_id": party_id, "player": player_name}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    if isinstance(payload, dict) and payload.get("position_token"):
        return payload
    return None


def fetch_party_names(page_url: str) -> list[str]:
    parsed_root = page_url.rstrip("/")
    try:
        with urlopen(f"{parsed_root}/health", timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    names = payload.get("names", []) if isinstance(payload, dict) else []
    if not isinstance(names, list):
        return []
    return [str(name) for name in names if isinstance(name, str) and name]


def voice_join_url(*, player: str = "", code: str = "", ptt: dict | None = None) -> str:
    base = friend_voice_url()
    extra: dict[str, str] = {}
    if player:
        extra["player"] = player
        extra["auto"] = "1"
    if code:
        extra["code"] = code
    binding = normalize_ptt_binding(ptt) if ptt is not None else load_ptt_binding()
    if binding is None:
        binding = load_ptt_binding()
    extra["ptt_kind"] = str(binding["kind"])
    extra["ptt"] = ptt_wire_value(binding)
    extra["ptt_label"] = str(binding["label"])
    joiner = "&" if "?" in base else "?"
    return base + joiner + urlencode(extra)


def attach_voice(*, player_name: str = "", wait_seconds: float = 0.0) -> bool:
    """Open voice as this character. The page retries until they log in.

    Do not wait for a local claim file. voice_claims.json lives on the game
    server, not on a friend's TES3MP client, so the old wait_seconds loop
    just delayed the window by up to 20s and then opened anyway.
    """
    del wait_seconds
    url = voice_join_url(player=player_name)
    launch = open_voice_client(url=url)
    return launch.ok
