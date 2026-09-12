"""Bounded, fail-closed state for the MorrowFriends voice relay."""

from __future__ import annotations

import math
import re
import secrets
import time
from dataclasses import dataclass

from app.voice import (
    PositionSnapshot,
    acoustic_environment,
    distance_between,
    listener_space_position,
    parse_position_snapshot,
    proximity_mix,
)

MAX_PLAYERS = 64
MAX_CLAIMS = 64
MAX_PLAYER_NAME_LENGTH = 64
MAX_CELL_NAME_LENGTH = 256
MAX_CLAIM_LIFETIME_MS = 10 * 60 * 1000
MAX_OBSERVED_AGE_MS = 7 * 24 * 60 * 60 * 1000
CLAIM_PATTERN = re.compile(r"^[A-Z0-9]{16}$")


class RelayError(ValueError):
    pass


@dataclass(frozen=True)
class VoiceSession:
    token: str
    player: str
    expires_at: float


class PartyState:
    """Latest-state position cache plus reliable, one-time identity claims."""

    def __init__(self, *, stale_timeout: float = 2.0, session_ttl: float = 600.0):
        self.stale_timeout = stale_timeout
        self.session_ttl = session_ttl
        self.snapshot = PositionSnapshot(0, 0, 0, 0.0, ())
        self.claims: dict[str, dict] = {}
        self.redeemed_claims: dict[str, int] = {}
        self.sessions: dict[str, VoiceSession] = {}
        self.generation = 0

    def update_snapshot(self, payload: dict, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        rows = payload.get("players") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) > MAX_PLAYERS:
            raise RelayError("invalid or oversized player snapshot")
        observed_age_ms = payload.get("observedAgeMs", 0)
        if (
            not isinstance(observed_age_ms, (int, float))
            or not math.isfinite(float(observed_age_ms))
            or observed_age_ms < 0
            or observed_age_ms > MAX_OBSERVED_AGE_MS
        ):
            raise RelayError("snapshot has an invalid observation age")
        observed_at = current - float(observed_age_ms) / 1000.0
        snapshot = parse_position_snapshot(payload, observed_at=observed_at)
        if snapshot.version != 1 or len(snapshot.players) != len(rows):
            raise RelayError("snapshot contains malformed player data")
        names = [player.name for player in snapshot.players]
        if len(set(names)) != len(names):
            raise RelayError("snapshot contains duplicate player names")
        if any(
            len(player.name) > MAX_PLAYER_NAME_LENGTH
            or len(player.cell) > MAX_CELL_NAME_LENGTH
            for player in snapshot.players
        ):
            raise RelayError("snapshot contains oversized player data")
        if snapshot.server_uptime_ms < self.snapshot.server_uptime_ms:
            # A new TES3MP process must not inherit claims or browser sessions
            # from the previous game-server lifetime.
            self.claims.clear()
            self.redeemed_claims.clear()
            self.sessions.clear()
        self.snapshot = snapshot
        self.redeemed_claims = {
            code: expires_at
            for code, expires_at in self.redeemed_claims.items()
            if expires_at > snapshot.server_uptime_ms
        }
        self.generation += 1

    def update_claims(self, payload: dict) -> None:
        raw_claims = payload.get("claims") if isinstance(payload, dict) else None
        if not isinstance(raw_claims, dict) or len(raw_claims) > MAX_CLAIMS:
            raise RelayError("invalid or oversized claim set")
        claims: dict[str, dict] = {}
        for raw_code, raw_claim in raw_claims.items():
            code = str(raw_code).strip().upper()
            if not CLAIM_PATTERN.fullmatch(code) or not isinstance(raw_claim, dict):
                raise RelayError("malformed voice claim")
            player = raw_claim.get("player")
            issued_at = raw_claim.get("issuedAtMs")
            expires_at = raw_claim.get("expiresAtMs")
            if (
                not isinstance(player, str)
                or not player
                or len(player) > MAX_PLAYER_NAME_LENGTH
                or not isinstance(issued_at, (int, float))
                or not isinstance(expires_at, (int, float))
                or expires_at <= issued_at
                or expires_at - issued_at > MAX_CLAIM_LIFETIME_MS
            ):
                raise RelayError("malformed voice claim")
            if code in self.redeemed_claims:
                continue
            claims[code] = {
                "player": player,
                "issuedAtMs": int(issued_at),
                "expiresAtMs": int(expires_at),
            }
        self.claims = claims
        self.generation += 1

    def redeem(self, code: str, *, now: float | None = None) -> VoiceSession:
        current = time.monotonic() if now is None else now
        normalized = code.strip().upper()
        claim = self.claims.get(normalized)
        if claim is None:
            raise RelayError("claim is invalid or has already been used")
        if self.snapshot.is_stale(now=current, timeout=self.stale_timeout):
            raise RelayError("game position feed is offline or stale")
        if claim["expiresAtMs"] <= self.snapshot.server_uptime_ms:
            self.claims.pop(normalized, None)
            raise RelayError("claim has expired")
        player = claim["player"]
        if player not in {pose.name for pose in self.snapshot.players}:
            raise RelayError("claimed player is not connected")

        # A fresh claim replaces any earlier browser session for that character.
        self.claims.pop(normalized, None)
        self.redeemed_claims[normalized] = int(claim["expiresAtMs"])
        self.sessions = {
            token: session
            for token, session in self.sessions.items()
            if session.player != player and session.expires_at > current
        }
        token = secrets.token_urlsafe(32)
        session = VoiceSession(token, player, current + self.session_ttl)
        self.sessions[token] = session
        self.generation += 1
        return session

    def redeem_for_player(self, player_name: str, *, now: float | None = None) -> VoiceSession:
        """Redeem the pending claim for a connected character without a typed code."""
        wanted = player_name.strip()
        if not wanted:
            raise RelayError("player name is required")
        match = next(
            (
                code
                for code, claim in self.claims.items()
                if str(claim.get("player", "")).casefold() == wanted.casefold()
            ),
            None,
        )
        if match is None:
            raise RelayError("no unused voice claim for that player")
        return self.redeem(match, now=now)

    def session(self, token: str, *, now: float | None = None) -> VoiceSession:
        current = time.monotonic() if now is None else now
        session = self.sessions.get(token)
        if session is None or session.expires_at <= current:
            self.sessions.pop(token, None)
            raise RelayError("voice session is invalid or expired")
        return session

    def player_frame(self, token: str, *, now: float | None = None) -> dict:
        current = time.monotonic() if now is None else now
        session = self.session(token, now=current)
        listener = next(
            (pose for pose in self.snapshot.players if pose.name == session.player), None
        )
        if listener is None:
            raise RelayError("player is no longer connected")
        stale = self.snapshot.is_stale(now=current, timeout=self.stale_timeout)
        gains = proximity_mix(
            self.snapshot,
            session.player,
            now=current,
            stale_timeout=self.stale_timeout,
        )
        speakers = []
        for speaker in self.snapshot.players:
            if speaker.name == session.player:
                continue
            distance = distance_between(listener, speaker)
            relative = listener_space_position(listener, speaker)
            speakers.append(
                {
                    "player": speaker.name,
                    "gain": gains.get(speaker.name, 0.0),
                    "distance": distance,
                    "position": None
                    if relative is None
                    else {
                        "right": relative[0],
                        "up": relative[1],
                        "forward": relative[2],
                    },
                }
            )
        return {
            "type": "mix",
            "sequence": self.snapshot.sequence,
            "stale": stale,
            "listener": session.player,
            "environment": acoustic_environment(listener),
            "speakers": speakers,
        }
