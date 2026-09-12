"""Small persisted launcher preferences shared across host and join flows."""

from __future__ import annotations

import base64
import ctypes
import json
import os
from dataclasses import dataclass
from ctypes import wintypes
from typing import Any

from .paths import settings_path
from .ptt_binding import DEFAULT_PTT_BINDING, normalize_ptt_binding


def _load() -> dict[str, Any]:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _save(data: dict[str, Any]) -> None:
    path = settings_path()
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(data, indent=2), encoding="utf-8")
    staging.replace(path)


def load_friend_share_url() -> str:
    value = _load().get("tailscale_machine_share_url", "")
    return value.strip() if isinstance(value, str) else ""


def save_friend_share_url(url: str) -> None:
    data = _load()
    data["tailscale_machine_share_url"] = url.strip()
    _save(data)


def load_host_player_name() -> str:
    """Return the host's pinned TES3MP account name, if one was selected."""
    value = _load().get("host_player_name", "")
    return value.strip() if isinstance(value, str) else ""


def save_host_player_name(player_name: str) -> None:
    """Persist the host identity independently of transient roster ordering."""
    data = _load()
    data["host_player_name"] = player_name.strip()
    _save(data)


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _protect_secret(secret: str) -> str:
    """Protect a host-only secret with the current Windows account's DPAPI key."""
    if not secret:
        return ""
    if os.name != "nt":
        raise OSError("Secure voice credential storage requires Windows")
    raw = secret.encode("utf-8")
    source_buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = _DataBlob(len(raw), source_buffer)
    protected = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "MorrowFriends voice host token",
        None,
        None,
        None,
        0x1,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(protected),
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(protected.pbData, protected.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        kernel32.LocalFree(protected.pbData)


def _unprotect_secret(encoded: str) -> str:
    if not encoded or os.name != "nt":
        return ""
    try:
        encrypted = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return ""
    source_buffer = (ctypes.c_ubyte * len(encrypted)).from_buffer_copy(encrypted)
    source = _DataBlob(len(encrypted), source_buffer)
    clear = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(clear)
    ):
        return ""
    try:
        return ctypes.string_at(clear.pbData, clear.cbData).decode("utf-8")
    except UnicodeDecodeError:
        return ""
    finally:
        kernel32.LocalFree(clear.pbData)


def load_app_mode() -> str:
    """Always start in friend mode.

    Hosting from a desktop PC is obsolete — the party runs on a real server, so
    the host cockpit (server name, port, Tailscale share, Start server, invite
    links) manages a server nobody uses any more. A machine left pinned to
    "host" from earlier testing opens on that dead cockpit with no Play button
    anywhere, which made the launcher appear unusable. Hosting is still
    reachable through the "I'm hosting" toggle for a local/LAN game.
    """
    _ = _load().get("app_mode", "friend")
    return "friend"


def save_app_mode(mode: str) -> None:
    data = _load()
    data["app_mode"] = "host" if mode == "host" else "friend"
    _save(data)


def load_first_run_complete() -> bool:
    return bool(_load().get("first_run_complete", False))


def save_first_run_complete(complete: bool = True) -> None:
    data = _load()
    data["first_run_complete"] = bool(complete)
    _save(data)


def load_last_invite_token() -> str:
    value = _load().get("last_invite_token", "")
    return value.strip() if isinstance(value, str) else ""


def save_last_invite_token(token: str) -> None:
    data = _load()
    data["last_invite_token"] = token.strip()
    _save(data)


def load_voice_enabled() -> bool:
    """False means Play must not open voice. Open voice still can."""
    value = _load().get("voice_enabled", True)
    return False if value is False else True


def save_voice_enabled(enabled: bool) -> None:
    data = _load()
    data["voice_enabled"] = bool(enabled)
    _save(data)


def load_ptt_binding() -> dict:
    parsed = normalize_ptt_binding(_load().get("ptt_binding"))
    return dict(parsed) if parsed is not None else dict(DEFAULT_PTT_BINDING)


def save_ptt_binding(binding: dict) -> dict:
    parsed = normalize_ptt_binding(binding) or dict(DEFAULT_PTT_BINDING)
    data = _load()
    data["ptt_binding"] = parsed
    _save(data)
    return parsed


def load_last_player_name() -> str:
    value = _load().get("last_player_name", "")
    return value.strip() if isinstance(value, str) else ""


def save_last_player_name(player_name: str) -> None:
    data = _load()
    name = player_name.strip()
    data["last_player_name"] = name
    # `or []` not `.get(key, [])` — a null in settings.json returns None from
    # the two-arg form and the comprehension below raises "'NoneType' object is
    # not iterable". Same defect class as tailscale.py's TailscaleIPs handling.
    names = data.get("known_player_names") or []
    if not isinstance(names, list):
        names = []
    known = [str(item).strip() for item in names if isinstance(item, str) and item.strip()]
    if name:
        known = [item for item in known if item.casefold() != name.casefold()]
        known.insert(0, name)
    data["known_player_names"] = known[:12]
    _save(data)


def load_known_player_names() -> list[str]:
    raw = _load().get("known_player_names", [])
    names: list[str] = []
    if isinstance(raw, list):
        names.extend(str(item).strip() for item in raw if isinstance(item, str) and item.strip())
    for extra in (load_last_player_name(), load_host_player_name()):
        if extra and extra.casefold() not in {name.casefold() for name in names}:
            names.insert(0, extra)
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def save_character_password(player_name: str, password: str) -> None:
    """Remember a TES3MP character password, encrypted to this Windows account.

    Players were being asked to invent a password at character creation and
    then recall it days later; rettycombine lost access on 2026-08-18 and it
    was UNRECOVERABLE, because TES3MP stores only a salted SHA-256 and there is
    no plaintext anywhere on the server. Remembering it locally is the only way
    a forgotten password stops meaning a lost character.

    DPAPI-protected, so the value is readable only by this Windows user on this
    machine and never sits in plaintext on disk.
    """
    name = player_name.strip()
    if not name:
        return
    data = _load()
    saved = data.get("character_passwords")
    if not isinstance(saved, dict):
        saved = {}
    if password:
        saved[name.casefold()] = _protect_secret(password)
    else:
        saved.pop(name.casefold(), None)
    data["character_passwords"] = saved
    _save(data)


def load_character_password(player_name: str) -> str:
    """Return a remembered character password, or "" when none is stored."""
    name = player_name.strip().casefold()
    if not name:
        return ""
    saved = _load().get("character_passwords")
    if not isinstance(saved, dict):
        return ""
    protected = saved.get(name, "")
    if not isinstance(protected, str) or not protected:
        return ""
    try:
        return _unprotect_secret(protected)
    except Exception:
        return ""


def known_character_names() -> list[str]:
    """Names that have a remembered password, for the launcher's picker."""
    saved = _load().get("character_passwords")
    if not isinstance(saved, dict):
        return []
    return sorted(str(key) for key in saved)
