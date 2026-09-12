"""Outbound-only bridge from a TES3MP host to the voice relay.

NOT wired into the launcher. The party runs on Skyhole, whose `voice_uplink`
service publishes positions and claims directly, so the launcher stopped
carrying relay credentials on 2026-08-21 — its only remaining voice job is the
loopback push-to-talk companion in `ptt_bridge`.

This module stays as the canonical implementation that `voice_uplink/app/
voice_relay.py` mirrors verbatim, so the wire protocol has exactly one owner.
Reconnect it here only if hosting a game from a desktop ever comes back; two
publishers cannot share a party, because the relay keeps a single host socket
and a lower `serverUptimeMs` makes it drop every claim and session.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

from .config import read_live_position_snapshot, read_voice_claims
from .paths import tes3mp_dir

MAX_ACK_BYTES = 4096
PARTY_ID_MAX_LENGTH = 64


class RelayConnection(Protocol):
    def send(self, message: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class VoiceRelaySettings:
    relay_url: str
    party_id: str
    host_token: str

    def validate(self) -> None:
        parsed = urlsplit(self.relay_url.strip())
        if parsed.scheme not in ("ws", "wss") or not parsed.hostname:
            raise ValueError("Voice relay URL must begin with wss://")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Voice relay URL cannot contain credentials, query, or fragment")
        if parsed.scheme == "ws" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Voice relay must use encrypted wss:// outside this computer")
        if (
            not self.party_id
            or len(self.party_id) > PARTY_ID_MAX_LENGTH
            or any(not (char.isascii() and (char.isalnum() or char in "_-")) for char in self.party_id)
        ):
            raise ValueError("Voice party ID must use 1-64 letters, numbers, _ or -")
        if len(self.host_token) < 32:
            raise ValueError("Voice host token must be at least 32 characters")

    @property
    def host_endpoint(self) -> str:
        self.validate()
        parsed = urlsplit(self.relay_url.strip())
        path = parsed.path.rstrip("/") + "/v1/host"
        return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))

    @property
    def friend_url(self) -> str:
        self.validate()
        parsed = urlsplit(self.relay_url.strip())
        scheme = "https" if parsed.scheme == "wss" else "http"
        path = parsed.path.rstrip("/") + "/"
        return urlunsplit(
            (scheme, parsed.netloc, path, urlencode({"party": self.party_id}), "")
        )


@dataclass(frozen=True)
class VoiceRelayStatus:
    state: str
    detail: str


@dataclass
class _SyncCursor:
    snapshot: str | None = None
    claims: str | None = None


def _canonical(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


class VoiceRelayBridge:
    """One bounded worker: coalesced positions, acknowledged identity claims."""

    def __init__(
        self,
        settings: VoiceRelaySettings,
        *,
        snapshot_source: Callable[[], dict] | None = None,
        claims_source: Callable[[], dict] | None = None,
        status_callback: Callable[[VoiceRelayStatus], None] | None = None,
        poll_interval: float = 0.2,
        ack_timeout: float = 3.0,
        wall_clock: Callable[[], float] = time.time,
    ):
        settings.validate()
        self.settings = settings
        self.snapshot_source = snapshot_source or (
            lambda: read_live_position_snapshot(tes3mp_dir())
        )
        self.claims_source = claims_source or (lambda: read_voice_claims(tes3mp_dir()))
        self.status_callback = status_callback
        self.poll_interval = poll_interval
        self.ack_timeout = ack_timeout
        self.wall_clock = wall_clock
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connection: RelayConnection | None = None
        self._connection_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="MorrowFriendsVoiceRelay",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        with self._connection_lock:
            connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:
                # Cleanup remains best-effort; the bounded worker still exits
                # through its stop event even if the transport is already broken.
                pass
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._status("stopped", "Voice relay stopped")

    def _status(self, state: str, detail: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(VoiceRelayStatus(state, detail))
        except Exception:
            # Status rendering must never terminate the network worker.
            return

    def _snapshot_message(self) -> tuple[str, dict] | None:
        payload = self.snapshot_source()
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return None
        file_mtime = payload.get("_fileMtime")
        if not isinstance(file_mtime, (int, float)):
            return None
        clean = {key: value for key, value in payload.items() if not key.startswith("_")}
        fingerprint = _canonical(clean)
        message = dict(clean)
        message.update(
            {
                "type": "snapshot",
                "partyId": self.settings.party_id,
                "observedAgeMs": max(0, int((self.wall_clock() - file_mtime) * 1000)),
            }
        )
        return fingerprint, message

    def _claims_message(self) -> tuple[str, dict] | None:
        payload = self.claims_source()
        if isinstance(payload, dict) and payload.get("_readError") is True:
            return None
        if not isinstance(payload, dict) or not isinstance(payload.get("claims"), dict):
            payload = {"version": 1, "claims": {}}
        clean = {key: value for key, value in payload.items() if not key.startswith("_")}
        fingerprint = _canonical(clean)
        message = dict(clean)
        message.update({"type": "claims", "partyId": self.settings.party_id})
        return fingerprint, message

    def _send_and_ack(self, connection: RelayConnection, kind: str, message: dict) -> None:
        connection.send(_canonical(message))
        raw = connection.recv(timeout=self.ack_timeout)
        if isinstance(raw, bytes):
            if len(raw) > MAX_ACK_BYTES:
                raise RuntimeError("Voice relay acknowledgement was too large")
            raw = raw.decode("utf-8")
        elif len(raw.encode("utf-8")) > MAX_ACK_BYTES:
            raise RuntimeError("Voice relay acknowledgement was too large")
        response = json.loads(raw)
        if response.get("type") != "ack" or response.get("kind") != kind:
            detail = response.get("error") if isinstance(response, dict) else None
            raise RuntimeError(detail or f"Voice relay did not acknowledge {kind}")

    def _sync_once(self, connection: RelayConnection, cursor: _SyncCursor) -> bool:
        sent = False
        snapshot = self._snapshot_message()
        if snapshot is not None and snapshot[0] != cursor.snapshot:
            self._send_and_ack(connection, "snapshot", snapshot[1])
            cursor.snapshot = snapshot[0]
            sent = True
        claims = self._claims_message()
        if claims is not None and claims[0] != cursor.claims:
            self._send_and_ack(connection, "claims", claims[1])
            cursor.claims = claims[0]
            sent = True
        return sent

    def _run_connected(self, connection: RelayConnection) -> None:
        cursor = _SyncCursor()
        self._status("connected", "Voice relay connected")
        while not self._stop_event.is_set():
            sent = self._sync_once(connection, cursor)
            if not sent and cursor.snapshot is None:
                self._status("waiting", "Voice relay is waiting for a live position feed")
            self._stop_event.wait(self.poll_interval)

    def _run(self) -> None:
        # Import lazily so the main launcher can still start with a clear error
        # if a development install is missing the optional transport package.
        try:
            from websockets.sync.client import connect
        except ImportError:
            self._status("error", "Voice relay transport is not installed")
            return

        delay = 1.0
        while not self._stop_event.is_set():
            self._status("connecting", "Connecting voice relay")
            try:
                with connect(
                    self.settings.host_endpoint,
                    additional_headers={
                        "Authorization": f"Bearer {self.settings.host_token}"
                    },
                    open_timeout=10,
                    close_timeout=2,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=MAX_ACK_BYTES,
                    max_queue=4,
                ) as connection:
                    with self._connection_lock:
                        self._connection = connection
                    delay = 1.0
                    self._run_connected(connection)
            except Exception as exc:
                if not self._stop_event.is_set():
                    self._status("error", f"Voice relay disconnected: {exc}")
            finally:
                with self._connection_lock:
                    self._connection = None
            if not self._stop_event.is_set():
                self._stop_event.wait(delay)
                delay = min(delay * 2.0, 30.0)
