"""Classify a TES3MP process exit so Play can heal once instead of looping."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol


class _Pollable(Protocol):
    def poll(self) -> int | None: ...


CRASH_WINDOW_SECONDS = 12.0


@dataclass(frozen=True)
class ProcessExit:
    kind: str
    action: str
    message: str


def classify_process_exit(
    proc: _Pollable | None,
    *,
    started_at: float,
    now: float | None = None,
    tes3mp_ok: bool = True,
    vc_ok: bool = True,
) -> ProcessExit | None:
    """Return None while the process is alive. One recovery action when it dies."""
    if proc is None:
        return None
    code = proc.poll()
    if code is None:
        return None
    elapsed = (time.monotonic() if now is None else now) - started_at
    if elapsed <= CRASH_WINDOW_SECONDS:
        if not vc_ok:
            return ProcessExit(
                "crash",
                "vc",
                "TES3MP closed immediately. The Microsoft C++ runtime is missing.",
            )
        if not tes3mp_ok:
            return ProcessExit(
                "crash",
                "repair",
                "TES3MP closed immediately. Repair the multiplayer engine, then Play.",
            )
        return ProcessExit(
            "crash",
            "repair",
            "TES3MP closed immediately. Repair TES3MP, then press Play.",
        )
    return ProcessExit("closed", "", "Game closed. Press Play when you are ready.")
