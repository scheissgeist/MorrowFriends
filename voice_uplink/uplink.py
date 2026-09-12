#!/usr/bin/env python3
"""Carry TES3MP positions from a Linux server to the voice relay.

Proximity voice needs a live position feed. On Windows that job belongs to
VoiceRelayBridge running inside the MorrowFriends launcher — which is why voice
died every time the launcher closed or crashed on 2026-08-18, and why the
Skyhole server had game but no voice: the Linux server writes
`live_players.json` correctly, but nothing was carrying it upstream.

This runs beside the game server instead, so voice no longer depends on anyone's
desktop being open.

It deliberately REUSES app/voice_relay.py rather than reimplementing the wire
protocol — the relay authenticates with a bearer token, expects versioned
snapshots with an observed age, and mutes the party when that age exceeds two
seconds. A second implementation would drift.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

# app/ ships alongside this file in the image so the bridge is the same code
# the launcher runs.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.voice_relay import VoiceRelayBridge, VoiceRelaySettings  # noqa: E402

# CoreScripts' dataPath sits one level below the server data mount: the
# entrypoint copies scripts to /server/data, and their JSON lands in
# /server/data/data. Getting this wrong yields an empty feed and a silent mute.
DATA_DIR = Path(os.environ.get("TES3MP_DATA", "/server/data/data"))
ROSTER_FILE = DATA_DIR / "live_players.json"
CLAIMS_FILE = DATA_DIR / "voice_claims.json"


def read_snapshot() -> dict:
    """Positions, stamped with the file's mtime so the relay can age them."""
    try:
        payload = json.loads(ROSTER_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or not isinstance(payload.get("players"), list):
        return {}
    payload["_fileMtime"] = ROSTER_FILE.stat().st_mtime
    return payload


def read_claims() -> dict:
    """code -> player, written by the roster Lua as characters log in."""
    try:
        payload = json.loads(CLAIMS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "claims": {}}
    except (OSError, json.JSONDecodeError):
        # Do NOT publish an empty claim set on a transient read error — that
        # would revoke every identity mid-session. Signal a read failure so the
        # bridge skips this cycle instead.
        return {"_readError": True}
    if isinstance(payload, dict) and isinstance(payload.get("claims"), dict):
        return payload
    return {"version": 1, "claims": {}}


def main() -> int:
    relay_url = os.environ.get("MORROWVOICE_RELAY_URL", "").strip()
    party_id = os.environ.get("MORROWVOICE_PARTY_ID", "").strip()
    host_token = os.environ.get("MORROWVOICE_HOST_TOKEN", "").strip()

    missing = [
        name
        for name, value in (
            ("MORROWVOICE_RELAY_URL", relay_url),
            ("MORROWVOICE_PARTY_ID", party_id),
            ("MORROWVOICE_HOST_TOKEN", host_token),
        )
        if not value
    ]
    if missing:
        print(f"[uplink] missing required env: {', '.join(missing)}", flush=True)
        return 2

    settings = VoiceRelaySettings(relay_url, party_id, host_token)
    try:
        settings.validate()
    except ValueError as exc:
        print(f"[uplink] bad relay settings: {exc}", flush=True)
        return 2

    def on_status(status) -> None:
        print(f"[uplink] {status.state}: {status.detail}", flush=True)

    bridge = VoiceRelayBridge(
        settings,
        snapshot_source=read_snapshot,
        claims_source=read_claims,
        status_callback=on_status,
    )

    stopping = {"now": False}

    def handle_signal(signum, _frame):
        print(f"[uplink] signal {signum}, stopping", flush=True)
        stopping["now"] = True
        bridge.stop(timeout=3.0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    print(f"[uplink] party={party_id} relay={relay_url}", flush=True)
    print(f"[uplink] reading {ROSTER_FILE}", flush=True)
    bridge.start()

    while not stopping["now"]:
        time.sleep(1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
