"""Authenticated HTTPS/WebSocket edge for MorrowFriends proximity voice."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from livekit import api
from pydantic import BaseModel, Field

from .core import PartyState, RelayError

PARTY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
LIVEKIT_NETLOC_PATTERN = re.compile(r"^[a-zA-Z0-9.-]+(?::[0-9]{1,5})?$")
MAX_HOST_MESSAGE_BYTES = 128 * 1024


@dataclass(frozen=True)
class VoiceRelayConfig:
    party_id: str
    host_token: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    token_ttl_seconds: int = 600

    @classmethod
    def from_env(cls) -> "VoiceRelayConfig":
        config = cls(
            party_id=os.environ.get("MORROWVOICE_PARTY_ID", ""),
            host_token=os.environ.get("MORROWVOICE_HOST_TOKEN", ""),
            livekit_url=os.environ.get("LIVEKIT_URL", ""),
            livekit_api_key=os.environ.get("LIVEKIT_API_KEY", ""),
            livekit_api_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not PARTY_PATTERN.fullmatch(self.party_id):
            raise ValueError("MORROWVOICE_PARTY_ID must be 1-64 safe URL characters")
        if len(self.host_token) < 32:
            raise ValueError("MORROWVOICE_HOST_TOKEN must be at least 32 characters")
        parsed_livekit = urlsplit(self.livekit_url)
        if (
            parsed_livekit.scheme not in {"wss", "ws"}
            or not parsed_livekit.hostname
            or not LIVEKIT_NETLOC_PATTERN.fullmatch(parsed_livekit.netloc)
            or parsed_livekit.username
            or parsed_livekit.password
            or parsed_livekit.query
            or parsed_livekit.fragment
        ):
            raise ValueError("LIVEKIT_URL must be a ws:// or wss:// URL")
        if not self.livekit_api_key or len(self.livekit_api_secret) < 32:
            raise ValueError("LiveKit API credentials are missing or too short")

    @property
    def room_name(self) -> str:
        return f"morrowfriends-{self.party_id}"

    @property
    def livekit_http_origin(self) -> str:
        parsed = urlsplit(self.livekit_url)
        scheme = "https" if parsed.scheme == "wss" else "http"
        return urlunsplit((scheme, parsed.netloc, "", "", ""))


class ClaimRequest(BaseModel):
    party_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=16, max_length=16)


class AutoClaimRequest(BaseModel):
    party_id: str = Field(min_length=1, max_length=64)
    player: str = Field(min_length=1, max_length=64)


class SlidingWindowLimiter:
    def __init__(
        self,
        *,
        attempts: int = 5,
        window_seconds: float = 60.0,
        max_keys: int = 4096,
    ):
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds
        for stale_key in list(self._events):
            stale_events = self._events[stale_key]
            while stale_events and stale_events[0] <= cutoff:
                stale_events.popleft()
            if not stale_events:
                del self._events[stale_key]
        events = self._events.get(key)
        if events is None:
            if len(self._events) >= self.max_keys:
                self._events.popitem(last=False)
            events = deque()
            self._events[key] = events
        else:
            self._events.move_to_end(key)
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.attempts:
            return False
        events.append(current)
        return True


def issue_livekit_token(config: VoiceRelayConfig, player: str) -> str:
    """Short-lived, microphone-only room token; API secrets never reach the browser."""
    return (
        api.AccessToken(config.livekit_api_key, config.livekit_api_secret)
        .with_identity(player)
        .with_name(player)
        .with_ttl(timedelta(seconds=config.token_ttl_seconds))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=config.room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
                can_publish_sources=["microphone"],
            )
        )
        .to_jwt()
    )


def _bearer(headers) -> str:
    value = headers.get("authorization", "")
    prefix = "Bearer "
    return value[len(prefix) :] if value.startswith(prefix) else ""


def create_app(config: VoiceRelayConfig) -> FastAPI:
    config.validate()
    app = FastAPI(title="MorrowFriends Voice Relay", docs_url=None, redoc_url=None)
    state = PartyState(session_ttl=float(config.token_ttl_seconds))
    # Claim codes have roughly 80 bits of entropy. A moderate bound stops noisy
    # automation without letting five typos lock an entire party behind an L4 proxy.
    limiter = SlidingWindowLimiter(attempts=30)
    app.state.party = state
    app.state.config = config
    app.state.host_socket = None

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "microphone=(self), camera=(), geolocation=(), display-capture=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self'; "
            "connect-src 'self' ws: wss: "
            f"{config.livekit_http_origin} http://127.0.0.1:47981; "
            "media-src 'self' blob:; "
            "img-src 'self' data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        if request.url.path == "/v1/claim":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health() -> dict:
        online = app.state.host_socket is not None and not state.snapshot.is_stale(
            timeout=state.stale_timeout
        )
        return {
            "ok": True,
            "party": config.party_id,
            "host_online": online,
            "players": len(state.snapshot.players) if online else 0,
            "names": [pose.name for pose in state.snapshot.players] if online else [],
        }

    @app.websocket("/v1/host")
    async def host_socket(websocket: WebSocket) -> None:
        supplied = _bearer(websocket.headers)
        if not supplied or not hmac.compare_digest(supplied, config.host_token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        previous = app.state.host_socket
        app.state.host_socket = websocket
        if previous is not None and previous is not websocket:
            await previous.close(code=4001, reason="Replaced by a new host connection")
        try:
            while True:
                raw = await websocket.receive_text()
                if len(raw.encode("utf-8")) > MAX_HOST_MESSAGE_BYTES:
                    await websocket.close(code=1009)
                    return
                try:
                    message = json.loads(raw)
                    if message.get("partyId") != config.party_id:
                        raise RelayError("wrong party")
                    kind = message.get("type")
                    if kind == "snapshot":
                        state.update_snapshot(message)
                    elif kind == "claims":
                        state.update_claims(message)
                    else:
                        raise RelayError("unknown host message")
                    await websocket.send_json(
                        {"type": "ack", "kind": kind, "generation": state.generation}
                    )
                except (json.JSONDecodeError, RelayError, TypeError, ValueError) as exc:
                    await websocket.send_json({"type": "error", "error": str(exc)})
        except WebSocketDisconnect:
            return
        finally:
            if app.state.host_socket is websocket:
                app.state.host_socket = None

    @app.post("/v1/claim")
    async def claim(body: ClaimRequest, request: Request) -> dict:
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            raise HTTPException(status_code=429, detail="Too many claim attempts")
        if body.party_id != config.party_id:
            raise HTTPException(status_code=404, detail="Party not found")
        try:
            session = state.redeem(body.code)
        except RelayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "server_url": config.livekit_url,
            "participant_token": issue_livekit_token(config, session.player),
            "participant_name": session.player,
            "participant_identity": session.player,
            "room_name": config.room_name,
            "position_token": session.token,
            "expires_in": config.token_ttl_seconds,
        }

    @app.post("/v1/auto-claim")
    async def auto_claim(body: AutoClaimRequest, request: Request) -> dict:
        client = request.client.host if request.client else "unknown"
        if not limiter.allow(client):
            raise HTTPException(status_code=429, detail="Too many claim attempts")
        if body.party_id != config.party_id:
            raise HTTPException(status_code=404, detail="Party not found")
        try:
            session = state.redeem_for_player(body.player)
        except RelayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "server_url": config.livekit_url,
            "participant_token": issue_livekit_token(config, session.player),
            "participant_name": session.player,
            "participant_identity": session.player,
            "room_name": config.room_name,
            "position_token": session.token,
            "expires_in": config.token_ttl_seconds,
        }

    @app.websocket("/v1/player")
    async def player_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
            if len(raw.encode("utf-8")) > 2048:
                raise RelayError("authentication message is too large")
            auth = json.loads(raw)
            if auth.get("type") != "auth" or not isinstance(auth.get("token"), str):
                raise RelayError("position session authentication required")
            token = auth["token"]
            state.session(token)
        except (asyncio.TimeoutError, json.JSONDecodeError, RelayError, TypeError, ValueError):
            await websocket.close(code=4401)
            return

        last_frame = None
        try:
            while True:
                try:
                    frame = state.player_frame(token)
                except RelayError:
                    await websocket.close(code=4401)
                    return
                encoded = json.dumps(frame, separators=(",", ":"), sort_keys=True)
                if encoded != last_frame:
                    await websocket.send_text(encoded)
                    last_frame = encoded
                await asyncio.sleep(0.2)
        except WebSocketDisconnect:
            return

    static_dir = Path(__file__).with_name("static")

    @app.get("/", include_in_schema=False)
    async def voice_page():
        return FileResponse(static_dir / "index.html")

    app.mount(
        "/assets",
        StaticFiles(directory=static_dir, check_dir=True),
        name="voice-assets",
    )

    return app


def app_from_env() -> FastAPI:
    return create_app(VoiceRelayConfig.from_env())
