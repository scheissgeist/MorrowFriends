#!/usr/bin/env python3
"""Stop a disconnect mid-combat from aborting the whole server.

packetReader.lua binds `player = Players[pid]` for ObjectActivate, ObjectHit,
ObjectSound and ConsoleCommand packets, then writes through `player` in every
branch below. A client whose packets are still in flight when it drops leaves
`Players[pid]` nil, so the write raises. TES3MP treats any Lua error as fatal,
so one player's disconnect aborts the process and takes everyone else with it.

Two edits, mirroring the nil-guard idiom CoreScripts already uses elsewhere in
this same file:

1. Bind a scratch table when the pid is gone, so the writes land somewhere
   harmless instead of raising.
2. Drop that scratch table at the tail by requiring the pid to still be live,
   so a departed player is never added to the packet tables.

Idempotent: refuses to apply twice. Path defaults to the Skyhole bind-mount;
pass another path as argv[1] (tests, a fresh image).
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

DEFAULT_PATH = Path("/opt/morrowfriends/tes3mp-server/data/scripts/packetReader.lua")

BIND_OLD = """            if isObjectPlayer then
                pid = tes3mp.GetObjectPid(packetIndex)
                player = Players[pid]
            else
"""

BIND_NEW = """            if isObjectPlayer then
                pid = tes3mp.GetObjectPid(packetIndex)
                player = Players[pid]

                -- A player can disconnect while their own packets are still in
                -- flight. Every branch below writes through `player`, and
                -- TES3MP treats a Lua error as fatal, so indexing a freed pid
                -- aborts the process and disconnects everyone. Absorb those
                -- writes into a scratch table; the tail below discards it
                -- because Players[pid] is gone.
                if player == nil then
                    player = {}
                end
            else
"""

TAIL_OLD = """        elseif player ~= nil then
            packetTables.players[pid] = player
        end
"""

TAIL_NEW = """        elseif player ~= nil and Players[pid] ~= nil then
            packetTables.players[pid] = player
        end
"""


def apply(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    if "Absorb those" in source:
        return "already patched"
    for label, needle in (("bind", BIND_OLD), ("tail", TAIL_OLD)):
        found = source.count(needle)
        if found != 1:
            raise RuntimeError(f"{label} anchor matched {found} times, expected 1")
    backup = path.with_name(path.name + f".bak.{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}")
    shutil.copy2(path, backup)
    path.write_text(
        source.replace(BIND_OLD, BIND_NEW).replace(TAIL_OLD, TAIL_NEW),
        encoding="utf-8",
    )
    return f"patched, backup at {backup}"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else DEFAULT_PATH
    print(apply(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
