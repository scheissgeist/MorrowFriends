"""Loopback-only global push-to-talk state for the browser voice client.

Browsers stop delivering keyboard events when the game owns focus.  This tiny
desktop companion polls one explicitly requested Windows key and streams only a
boolean pressed state to an allow-listed MorrowFriends voice origin.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


PTT_BRIDGE_HOST = "127.0.0.1"
PTT_BRIDGE_PORT = 47981
VOICE_CLIENT_CONFIG_NAME = "MorrowFriends.voice.json"


_NAMED_VIRTUAL_KEYS = {
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "ShiftLeft": 0xA0,
    "ShiftRight": 0xA1,
    "ControlLeft": 0xA2,
    "ControlRight": 0xA3,
    "AltLeft": 0xA4,
    "AltRight": 0xA5,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "Escape": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "ArrowLeft": 0x25,
    "ArrowUp": 0x26,
    "ArrowRight": 0x27,
    "ArrowDown": 0x28,
    "PrintScreen": 0x2C,
    "Insert": 0x2D,
    "Delete": 0x2E,
    "MetaLeft": 0x5B,
    "MetaRight": 0x5C,
    "NumpadMultiply": 0x6A,
    "NumpadAdd": 0x6B,
    "NumpadSubtract": 0x6D,
    "NumpadDecimal": 0x6E,
    "NumpadDivide": 0x6F,
    "NumLock": 0x90,
    "ScrollLock": 0x91,
    "Semicolon": 0xBA,
    "Equal": 0xBB,
    "Comma": 0xBC,
    "Minus": 0xBD,
    "Period": 0xBE,
    "Slash": 0xBF,
    "Backquote": 0xC0,
    "BracketLeft": 0xDB,
    "Backslash": 0xDC,
    "BracketRight": 0xDD,
    "Quote": 0xDE,
}
_MOUSE_VIRTUAL_KEYS = {0: 0x01, 1: 0x04, 2: 0x02, 3: 0x05, 4: 0x06}


def keyboard_virtual_key(code: str) -> int | None:
    if code in _NAMED_VIRTUAL_KEYS:
        return _NAMED_VIRTUAL_KEYS[code]
    if len(code) == 4 and code.startswith("Key") and code[3].isalpha():
        return ord(code[3].upper())
    if len(code) == 6 and code.startswith("Digit") and code[5].isdigit():
        return ord(code[5])
    if code.startswith("Numpad") and code[6:].isdigit() and len(code[6:]) == 1:
        return 0x60 + int(code[6:])
    if code.startswith("F") and code[1:].isdigit():
        number = int(code[1:])
        if 1 <= number <= 24:
            return 0x6F + number
    return None


def binding_virtual_key(kind: str, value: str) -> int | None:
    if kind == "keyboard":
        return keyboard_virtual_key(value)
    if kind == "mouse":
        try:
            return _MOUSE_VIRTUAL_KEYS.get(int(value))
        except ValueError:
            return None
    return None


def voice_config_candidates() -> list[Path]:
    """Return packaged and development paths for MorrowFriends.voice.json."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().with_name(VOICE_CLIENT_CONFIG_NAME))
    candidates.append(Path(__file__).resolve().parents[1] / "packaging" / VOICE_CLIENT_CONFIG_NAME)
    return candidates


def load_allowed_voice_origins() -> set[str]:
    """Load public, non-secret voice origins shipped beside the launcher."""
    for path in voice_config_candidates():
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        values = raw.get("allowed_origins", []) if isinstance(raw, dict) else []
        if not isinstance(values, list):
            continue
        origins = {origin for value in values if (origin := normalize_https_origin(value))}
        if origins:
            return origins
    return set()


def normalize_https_origin(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return None
    return f"https://{parsed.netloc.lower()}"


def voice_origin_from_url(value: object) -> str | None:
    """Return the HTTPS page origin for an HTTPS or WSS relay URL."""
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"https", "wss"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return f"https://{parsed.netloc.lower()}"


@dataclass(frozen=True)
class PttBridgeStatus:
    running: bool
    detail: str


class _PttHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, bridge: "LocalPttBridge") -> None:
        self.bridge = bridge
        super().__init__((PTT_BRIDGE_HOST, bridge.port), _PttHandler)


class _PttHandler(BaseHTTPRequestHandler):
    server: _PttHttpServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _reject(self, status: HTTPStatus, detail: str) -> None:
        body = json.dumps({"detail": detail}, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlsplit(self.path)
        if parsed.path != "/v1/ptt/events":
            self._reject(HTTPStatus.NOT_FOUND, "Not found")
            return
        origin = self.headers.get("Origin", "")
        if not self.server.bridge.origin_allowed(origin):
            self._reject(HTTPStatus.FORBIDDEN, "Voice origin is not approved by MorrowFriends")
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        kind = query.get("kind", [""])[0]
        value = query.get("value", [""])[0]
        virtual_key = binding_virtual_key(kind, value)
        if virtual_key is None:
            self._reject(HTTPStatus.BAD_REQUEST, "Unsupported push-to-talk binding")
            return
        self.server.bridge.remember_binding(virtual_key)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while not self.server.bridge.stopping:
                pressed = self.server.bridge.key_pressed(virtual_key)
                payload = b'data: {"pressed":' + (b"true" if pressed else b"false") + b"}\n\n"
                self.wfile.write(payload)
                self.wfile.flush()
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


class LocalPttBridge:
    """Serve global key state only on loopback and only to approved origins."""

    def __init__(self, allowed_origins: set[str] | None = None, *, port: int = PTT_BRIDGE_PORT) -> None:
        self.port = port
        self._allowed_origins = {
            normalized
            for value in (allowed_origins or set())
            if (normalized := normalize_https_origin(value))
        }
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server: _PttHttpServer | None = None
        self._thread: threading.Thread | None = None
        self._last_virtual_key = _NAMED_VIRTUAL_KEYS["Space"]

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def origin_allowed(self, origin: str) -> bool:
        normalized = normalize_https_origin(origin)
        with self._lock:
            return normalized is not None and normalized in self._allowed_origins

    def add_allowed_origin(self, value: str) -> bool:
        normalized = normalize_https_origin(value)
        if normalized is None:
            return False
        with self._lock:
            self._allowed_origins.add(normalized)
        return True

    def remember_binding(self, virtual_key: int) -> None:
        with self._lock:
            self._last_virtual_key = virtual_key

    def last_virtual_key(self) -> int:
        with self._lock:
            return self._last_virtual_key

    def talking(self) -> bool:
        return self.key_pressed(self.last_virtual_key())

    def key_pressed(self, virtual_key: int) -> bool:
        if os.name != "nt":
            return False
        return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def start(self) -> PttBridgeStatus:
        if os.name != "nt":
            return PttBridgeStatus(False, "Global PTT requires Windows")
        if self._thread is not None and self._thread.is_alive():
            return PttBridgeStatus(True, "Global PTT companion is ready")
        try:
            self._server = _PttHttpServer(self)
        except OSError:
            return PttBridgeStatus(False, "Another MorrowFriends PTT companion is already running")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="morrowfriends-ptt",
            daemon=True,
        )
        self._thread.start()
        return PttBridgeStatus(True, "Global PTT companion is ready")

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        server = self._server
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        self._server = None
        self._thread = None
