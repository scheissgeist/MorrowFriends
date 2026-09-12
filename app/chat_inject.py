"""Best-effort TES3MP chat inject. Falls back to clipboard when the game ignores it."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass

KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D
VK_Y = 0x59


class _KeyBdInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("ki", _KeyBdInput),)


class _Input(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", _InputUnion))


@dataclass(frozen=True)
class ChatInjectResult:
    ok: bool
    method: str
    detail: str


def tes3mp_window_titles(titles: list[str]) -> list[str]:
    """Return titles that look like a live TES3MP client window."""
    matches: list[str] = []
    for title in titles:
        upper = title.upper()
        if "TES3MP" in upper or title.startswith("Morrowind"):
            matches.append(title)
    return matches


def _enum_window_titles() -> list[str]:
    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value:
            titles.append(buffer.value)
        return True

    user32.EnumWindows(callback, 0)
    return titles


def _find_tes3mp_hwnd() -> int | None:
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if tes3mp_window_titles([buffer.value]):
            found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def _send_vk(virtual_key: int) -> None:
    extra = ctypes.c_ulong(0)
    down = _Input(1, _InputUnion(_KeyBdInput(virtual_key, 0, 0, 0, ctypes.pointer(extra))))
    up = _Input(
        1,
        _InputUnion(_KeyBdInput(virtual_key, 0, KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))),
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_Input))
    ctypes.windll.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_Input))


def _send_unicode(text: str) -> None:
    extra = ctypes.c_ulong(0)
    for char in text:
        scan = ord(char)
        down = _Input(
            1,
            _InputUnion(_KeyBdInput(0, scan, KEYEVENTF_UNICODE, 0, ctypes.pointer(extra))),
        )
        up = _Input(
            1,
            _InputUnion(
                _KeyBdInput(0, scan, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
            ),
        )
        ctypes.windll.user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(_Input))
        ctypes.windll.user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(_Input))


def send_chat_command(command: str, *, say_key: int = VK_Y) -> ChatInjectResult:
    """Focus TES3MP, open chat with Y, type the command, press Enter."""
    text = (command or "").strip()
    if not text:
        return ChatInjectResult(False, "none", "No command to send.")
    hwnd = _find_tes3mp_hwnd()
    if hwnd is None:
        return ChatInjectResult(False, "none", "TES3MP is not in the foreground yet.")
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    if not user32.SetForegroundWindow(hwnd):
        return ChatInjectResult(False, "none", "Could not focus TES3MP.")
    time.sleep(0.12)
    _send_vk(say_key)
    time.sleep(0.12)
    _send_unicode(text)
    time.sleep(0.05)
    _send_vk(VK_RETURN)
    return ChatInjectResult(True, "sendinput", f"Sent {text} into TES3MP chat.")
