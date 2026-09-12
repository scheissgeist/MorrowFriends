"""Fallback: open the proximity voice page in its own window.

Voice normally renders INSIDE the launcher window — see `app/voice_embed.py`.
This module is what runs when that is impossible, e.g. no WebView2 runtime.
Push-to-talk still uses the local loopback companion; game positions still come
from the outbound host relay.
"""

from __future__ import annotations

import json
import os
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from .ptt_bridge import VOICE_CLIENT_CONFIG_NAME, voice_config_candidates, voice_origin_from_url


DEFAULT_VOICE_PAGE = "https://voice.gamebrain.win/"
DEFAULT_VOICE_PARTY = "broteam-morrowind"


@dataclass(frozen=True)
class VoiceClientConfig:
    page_url: str
    party_id: str
    allowed_origins: frozenset[str]

    @property
    def join_url(self) -> str:
        parsed = urlsplit(self.page_url)
        query = urlencode({"party": self.party_id})
        path = parsed.path or "/"
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))


def _load_voice_client_file() -> dict:
    for path in voice_config_candidates():
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(raw, dict):
            return raw
    return {}


def load_voice_client_config() -> VoiceClientConfig:
    """Resolve the public voice page from the shipped defaults.

    There is one server and one voice party, and the game server publishes its
    own positions to the relay, so there is nothing here for a user to
    configure. The launcher-side relay settings were removed on 2026-08-21.
    """
    raw = _load_voice_client_file()
    allowed: set[str] = set()
    values = raw.get("allowed_origins", [])
    if isinstance(values, list):
        for value in values:
            origin = voice_origin_from_url(value) if isinstance(value, str) else None
            if origin:
                allowed.add(origin)

    page = raw.get("default_page", DEFAULT_VOICE_PAGE)
    if not isinstance(page, str) or not page.strip():
        page = DEFAULT_VOICE_PAGE
    page = page.strip()
    if not page.endswith("/"):
        page += "/"

    party = raw.get("default_party", DEFAULT_VOICE_PARTY)
    if not isinstance(party, str) or not party.strip():
        party = DEFAULT_VOICE_PARTY
    party = party.strip()

    page_origin = voice_origin_from_url(page)
    if page_origin:
        allowed.add(page_origin)
    if not allowed:
        allowed.add("https://voice.gamebrain.win")

    return VoiceClientConfig(page, party, frozenset(allowed))


def friend_voice_url() -> str:
    return load_voice_client_config().join_url


def _edge_candidates() -> list[Path]:
    roots = [
        os.environ.get("PROGRAMFILES(X86)") or r"C:\Program Files (x86)",
        os.environ.get("PROGRAMFILES") or r"C:\Program Files",
        os.environ.get("LOCALAPPDATA") or "",
    ]
    names = [
        Path("Microsoft") / "Edge" / "Application" / "msedge.exe",
        Path("Microsoft") / "Edge SxS" / "Application" / "msedge.exe",
    ]
    found: list[Path] = []
    for root in roots:
        if not root:
            continue
        base = Path(root)
        for name in names:
            candidate = base / name
            if candidate.is_file():
                found.append(candidate)
    return found


def _open_edge_app(url: str) -> bool:
    for edge in _edge_candidates():
        try:
            subprocess.Popen(
                [str(edge), f"--app={url}", "--new-window"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except OSError:
            continue
    return False


def _open_system_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        return False


@dataclass(frozen=True)
class VoiceClientLaunch:
    ok: bool
    method: str
    url: str
    detail: str


def open_voice_client(*, url: str | None = None) -> VoiceClientLaunch:
    """Open proximity voice in a separate window.

    This is now the FALLBACK path. Voice normally renders inside the launcher
    window via `voice_embed.VoiceEmbedder`; this runs only when WebView2 cannot
    be hosted at all.

    There used to be a pywebview branch ahead of these. It could never succeed:
    pywebview 5 raises "pywebview must be run on a main thread" and the
    launcher's main thread belongs to Tk. Worse, it reported success by
    returning True the instant the thread was spawned, so the first click on
    Open voice opened nothing, said it had worked, and only the SECOND click
    reached the Edge fallback below.
    """
    target = (url or friend_voice_url()).strip()
    if not target.startswith("https://"):
        return VoiceClientLaunch(
            False, "none", target, "Voice page must be an https:// URL"
        )

    if _open_edge_app(target):
        return VoiceClientLaunch(
            True, "edge-app", target, "Opened voice in a separate Edge window."
        )
    if _open_system_browser(target):
        return VoiceClientLaunch(
            True, "browser", target, "Opened voice in your browser."
        )
    return VoiceClientLaunch(
        False,
        "none",
        target,
        "Could not open the voice client. Install Microsoft Edge WebView2 or Edge.",
    )


def shipped_voice_config_name() -> str:
    return VOICE_CLIENT_CONFIG_NAME
