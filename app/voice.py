"""Authoritative TES3MP position model and proximity rules for voice."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass


_CAVERN_CELL_MARKERS = (
    "barrow",
    "burial",
    "canalworks",
    "cave",
    "cavern",
    "crypt",
    "egg mine",
    "mine",
    "sewer",
    "tomb",
    "underworks",
)
_LARGE_INTERIOR_CELL_MARKERS = (
    "arena",
    "castle",
    "fort",
    "guild",
    "hall",
    "palace",
    "plaza",
    "shrine",
    "stronghold",
    "temple",
    "tower",
    "waistworks",
)


@dataclass(frozen=True)
class PlayerPose:
    name: str
    cell: str
    exterior: bool
    x: float
    y: float
    z: float
    rot_x: float
    rot_z: float


@dataclass(frozen=True)
class PositionSnapshot:
    version: int
    sequence: int
    server_uptime_ms: int
    observed_at: float
    players: tuple[PlayerPose, ...]

    def is_stale(self, *, now: float | None = None, timeout: float = 2.0) -> bool:
        current = time.monotonic() if now is None else now
        return current - self.observed_at > timeout


def _finite_number(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("position component is not finite")
    return number


def parse_position_snapshot(
    payload: dict, *, observed_at: float | None = None
) -> PositionSnapshot:
    """Parse a bridge snapshot, dropping malformed player rows safely."""
    players: list[PlayerPose] = []
    rows = payload.get("players", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        position = row.get("position")
        rotation = row.get("rotation")
        name = row.get("name")
        cell = row.get("cell")
        if not isinstance(name, str) or not name or not isinstance(cell, str):
            continue
        if not isinstance(position, dict) or not isinstance(rotation, dict):
            continue
        try:
            players.append(
                PlayerPose(
                    name=name,
                    cell=cell,
                    exterior=bool(row.get("exterior")),
                    x=_finite_number(position.get("x")),
                    y=_finite_number(position.get("y")),
                    z=_finite_number(position.get("z")),
                    rot_x=_finite_number(rotation.get("x")),
                    rot_z=_finite_number(rotation.get("z")),
                )
            )
        except (TypeError, ValueError):
            continue
    return PositionSnapshot(
        version=int(payload.get("version", 0) or 0),
        sequence=int(payload.get("sequence", 0) or 0),
        server_uptime_ms=int(payload.get("serverUptimeMs", 0) or 0),
        observed_at=time.monotonic() if observed_at is None else observed_at,
        players=tuple(players),
    )


def distance_between(listener: PlayerPose, speaker: PlayerPose) -> float | None:
    """Return world distance, or None when the two players cannot hear each other."""
    if listener.exterior != speaker.exterior:
        return None
    if not listener.exterior and listener.cell != speaker.cell:
        return None
    return math.dist(
        (listener.x, listener.y, listener.z),
        (speaker.x, speaker.y, speaker.z),
    )


def listener_space_position(
    listener: PlayerPose, speaker: PlayerPose
) -> tuple[float, float, float] | None:
    """Return speaker coordinates as right, up, forward from the listener.

    OpenMW actors face +Y at zero Z rotation and rotate toward +X as Z
    rotation increases. Keeping this transform authoritative beside the
    distance rules prevents every browser client from guessing at game axes.
    """
    if distance_between(listener, speaker) is None:
        return None
    dx = speaker.x - listener.x
    dy = speaker.y - listener.y
    dz = speaker.z - listener.z
    sin_yaw = math.sin(listener.rot_z)
    cos_yaw = math.cos(listener.rot_z)
    right = dx * cos_yaw - dy * sin_yaw
    forward = dx * sin_yaw + dy * cos_yaw
    return right, dz, forward


def acoustic_environment(listener: PlayerPose) -> str:
    """Choose a restrained room profile from TES3MP's location metadata."""
    if listener.exterior:
        return "outdoors"
    cell = listener.cell.casefold()
    if any(marker in cell for marker in _CAVERN_CELL_MARKERS):
        return "cavern"
    if any(marker in cell for marker in _LARGE_INTERIOR_CELL_MARKERS):
        return "large-interior"
    return "interior"


def proximity_gain(
    listener: PlayerPose,
    speaker: PlayerPose,
    *,
    full_volume_distance: float = 500.0,
    silent_distance: float = 3000.0,
) -> float:
    """Linear distance attenuation with hard interior/exterior isolation."""
    if silent_distance <= full_volume_distance:
        raise ValueError("silent distance must exceed full-volume distance")
    distance = distance_between(listener, speaker)
    if distance is None or distance >= silent_distance:
        return 0.0
    if distance <= full_volume_distance:
        return 1.0
    return 1.0 - (distance - full_volume_distance) / (
        silent_distance - full_volume_distance
    )


def proximity_mix(
    snapshot: PositionSnapshot,
    listener_name: str,
    *,
    now: float | None = None,
    stale_timeout: float = 2.0,
    full_volume_distance: float = 500.0,
    silent_distance: float = 3000.0,
) -> dict[str, float]:
    """Calculate speaker gains, failing closed when the position feed is stale."""
    listener = next(
        (player for player in snapshot.players if player.name == listener_name), None
    )
    speakers = [player for player in snapshot.players if player.name != listener_name]
    if listener is None:
        return {}
    if snapshot.is_stale(now=now, timeout=stale_timeout):
        return {speaker.name: 0.0 for speaker in speakers}
    return {
        speaker.name: proximity_gain(
            listener,
            speaker,
            full_volume_distance=full_volume_distance,
            silent_distance=silent_distance,
        )
        for speaker in speakers
    }
