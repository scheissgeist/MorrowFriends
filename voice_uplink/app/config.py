"""Stub: satisfies voice_relay's default-source imports.

The real implementations live in the launcher's app/config.py, which cannot be
imported on Linux (it pulls detect.py -> winreg). The uplink passes its own
snapshot_source and claims_source, so these are never invoked.
"""
from pathlib import Path


def read_live_position_snapshot(tes3mp_root: Path) -> dict:
    raise RuntimeError("uplink must supply snapshot_source explicitly")


def read_voice_claims(tes3mp_root: Path) -> dict:
    raise RuntimeError("uplink must supply claims_source explicitly")
