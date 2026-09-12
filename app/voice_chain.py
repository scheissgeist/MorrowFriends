"""End-to-end diagnosis of the proximity-voice chain.

Positional voice only works when EVERY link is alive:

    TES3MP server (Lua timer, 200ms)
        -> server/data/live_players.json          [link 1]
        -> MorrowFriends relay bridge (200ms)     [link 2]
        -> Skyhole relay, mutes at 2000ms stale   [link 3]
        -> browser page + LiveKit media           [link 4]

On 2026-08-18 voice failed four separate times and each failure LOOKED the
same from the outside ("voice doesn't work"), while the actual broken link was
different every time: the game server had crashed, the launcher had been
closed, a claim was redeemed but the media connection failed, and once the
page was handed the host's identity instead of the player's.

This module answers "which link is down" in one call instead of four
investigations.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import read_live_position_snapshot, read_voice_claims

# The relay mutes a party whose newest snapshot is older than this. Matching
# the server's own constant (voice_service/core.py stale_timeout) so the
# launcher warns about the same threshold the relay enforces.
RELAY_STALE_SECONDS = 2.0


@dataclass(frozen=True)
class LinkStatus:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ChainReport:
    links: tuple[LinkStatus, ...]

    @property
    def ok(self) -> bool:
        return all(link.ok for link in self.links)

    @property
    def first_broken(self) -> LinkStatus | None:
        for link in self.links:
            if not link.ok:
                return link
        return None

    def summary(self) -> str:
        broken = self.first_broken
        if broken is None:
            return "Proximity voice chain is healthy."
        return f"{broken.name}: {broken.detail}"


def check_game_feed(tes3mp_root: Path, *, now: float | None = None) -> LinkStatus:
    """Link 1 - is the TES3MP server writing live positions?"""
    current = time.time() if now is None else now
    snapshot = read_live_position_snapshot(tes3mp_root)
    if not snapshot:
        return LinkStatus(
            "Game feed",
            False,
            "no position file yet — start the server, then log in.",
        )
    if snapshot.get("version") != 1:
        # A bare {} from an older OnServerExit handler lands here. The bridge
        # refuses to publish it, so the relay silently receives nothing.
        return LinkStatus(
            "Game feed",
            False,
            "position file is not a versioned snapshot — restart the server.",
        )
    mtime = snapshot.get("_fileMtime")
    age = None if not isinstance(mtime, (int, float)) else current - mtime
    players = snapshot.get("players")
    count = len(players) if isinstance(players, list) else 0
    if age is not None and age > RELAY_STALE_SECONDS:
        return LinkStatus(
            "Game feed",
            False,
            f"positions are {age:.1f}s old — the server is stopped or frozen "
            "(the relay mutes everyone past "
            f"{RELAY_STALE_SECONDS:.0f}s).",
        )
    if count == 0:
        return LinkStatus(
            "Game feed",
            True,
            "server is publishing, nobody logged in yet.",
        )
    return LinkStatus("Game feed", True, f"{count} player(s) publishing positions.")


def check_claims(tes3mp_root: Path) -> LinkStatus:
    """Link 2 - does the server know who each connected character is?"""
    payload = read_voice_claims(tes3mp_root)
    if payload.get("_readError") is True:
        return LinkStatus("Identity", False, "voice_claims.json could not be read.")
    claims = payload.get("claims")
    if not isinstance(claims, dict) or not claims:
        return LinkStatus(
            "Identity",
            True,
            "no claims yet — these appear as characters log in.",
        )
    names = sorted(
        str(entry.get("player", "?"))
        for entry in claims.values()
        if isinstance(entry, dict)
    )
    return LinkStatus("Identity", True, "claims ready for: " + ", ".join(names))


def check_relay(page_url: str, party_id: str, *, timeout: float = 6.0) -> LinkStatus:
    """Links 3 and 4 - is the relay up, and does it see this party's host?"""
    root = page_url.rstrip("/")
    if not root:
        return LinkStatus("Relay", False, "no relay URL configured.")
    try:
        with urllib.request.urlopen(f"{root}/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return LinkStatus("Relay", False, f"unreachable ({exc}).")
    if not isinstance(payload, dict) or not payload.get("ok"):
        return LinkStatus("Relay", False, "relay reported an error.")
    if party_id and payload.get("party") not in (None, party_id):
        return LinkStatus(
            "Relay",
            False,
            f"relay is serving party {payload.get('party')!r}, not {party_id!r}.",
        )
    if not payload.get("host_online"):
        # The launcher IS the uplink. This is the link that broke most often on
        # 2026-08-18, because closing or crashing MorrowFriends kills it while
        # the game server keeps running and everything else still looks fine.
        return LinkStatus(
            "Relay uplink",
            False,
            "the relay is up but MorrowFriends is not feeding it — keep the "
            "launcher running while you play.",
        )
    names = payload.get("names")
    count = len(names) if isinstance(names, list) else 0
    return LinkStatus("Relay", True, f"connected, {count} player(s) in voice.")


def diagnose(
    tes3mp_root: Path,
    page_url: str,
    party_id: str,
    *,
    now: float | None = None,
    timeout: float = 6.0,
) -> ChainReport:
    """Walk the whole chain and report the FIRST broken link."""
    return ChainReport(
        (
            check_game_feed(tes3mp_root, now=now),
            check_claims(tes3mp_root),
            check_relay(page_url, party_id, timeout=timeout),
        )
    )
