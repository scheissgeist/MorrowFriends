"""Friend-safe recovery helpers. Play stays automatic; this is the escape hatch."""

from __future__ import annotations

import re

from .play import PlayError

VOICE_CODE = re.compile(r"^[A-Z0-9]{16}$")

# Only the actions a friend can actually be handed. "tailscale" and "share"
# went with the public server — there is no account to make and no device share
# to accept. "invite" survives because play.py can still raise it if the party
# host is ever a Tailscale address again, but it now opens Settings rather than
# asking for a link to paste: the paste field was removed on 2026-08-18.
RECOVERY_ACTION_LABELS = {
    "browse": "Find Morrowind",
    "vc": "Install C++ runtime",
    "invite": "Open settings",
    "voice": "Open voice",
    "repair": "Repair TES3MP",
}


def normalize_voice_code(text: str) -> str:
    """Empty is fine (just open voice). A typed code must be the 16-character /voice value."""
    code = re.sub(r"\s+", "", text or "").upper()
    if not code:
        return ""
    if not VOICE_CODE.fullmatch(code):
        raise PlayError(
            "Voice codes are 16 letters and numbers from /voice in chat.",
            action="voice",
        )
    return code
