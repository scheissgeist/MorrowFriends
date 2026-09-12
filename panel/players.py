"""Player-record administration for the MorrowFriends web panel.

Reads and writes the same TES3MP JSON records the desktop launcher touches,
so the panel works with no launcher running.

NEVER leaves a record with a name but no credentials. That state does not
produce a fresh registration — HasAccount() is true whenever the file loads, so
the server shows the LOGIN dialog and CoreScripts eventHandler.lua then
concatenates a nil salt, which kills the entire server process
(ucrtbase 0xc0000409). It happened five times on 2026-08-18.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

SALT_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
OWNER_RANK = 3


@dataclass(frozen=True)
class PlayerRecord:
    name: str
    staff_rank: int
    console_allowed: bool
    has_credentials: bool
    cell: str
    expelled_from: tuple[str, ...]


def _player_dir(data_root: Path) -> Path:
    return data_root / "player"


def _expulsion_table(record: dict) -> dict:
    """The player's faction expulsion map.

    CoreScripts serialises an empty Lua table as a JSON array, so a player who
    has never been expelled stores `[]` rather than `{}`.
    """
    table = record.get("factionExpulsion")
    return table if isinstance(table, dict) else {}


def _load(path: Path) -> dict | None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def _save(path: Path, record: dict) -> None:
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(record, indent=2), encoding="utf-8")
    staging.replace(path)


def list_players(data_root: Path) -> list[PlayerRecord]:
    folder = _player_dir(data_root)
    if not folder.is_dir():
        return []
    rows: list[PlayerRecord] = []
    for path in sorted(folder.glob("*.json")):
        record = _load(path)
        if record is None:
            continue
        settings = record.get("settings")
        settings = settings if isinstance(settings, dict) else {}
        login = record.get("login")
        login = login if isinstance(login, dict) else {}
        location = record.get("location")
        location = location if isinstance(location, dict) else {}
        rank = settings.get("staffRank")
        expelled = tuple(
            sorted(
                faction_id
                for faction_id, state in _expulsion_table(record).items()
                if state is True
            )
        )
        rows.append(
            PlayerRecord(
                name=path.stem,
                staff_rank=rank if isinstance(rank, int) else 0,
                console_allowed=settings.get("consoleAllowed") is True,
                has_credentials=bool(login.get("passwordHash") and login.get("passwordSalt")),
                cell=str(location.get("cell", "")),
                expelled_from=expelled,
            )
        )
    return rows


def broken_accounts(data_root: Path) -> list[str]:
    """Records that would crash the server when that player logs in."""
    return [row.name for row in list_players(data_root) if not row.has_credentials]


def set_staff_rank(data_root: Path, name: str, rank: int, console: bool) -> bool:
    path = _player_dir(data_root) / f"{name}.json"
    record = _load(path)
    if record is None:
        return False
    settings = record.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    settings["staffRank"] = int(rank)
    settings["consoleAllowed"] = bool(console)
    record["settings"] = settings
    _save(path, record)
    check = _load(path) or {}
    verify = check.get("settings", {})
    return verify.get("staffRank") == int(rank) and verify.get("consoleAllowed") is bool(console)


def clear_expulsions(data_root: Path, name: str) -> bool:
    """Lift every guild expulsion on one SAVED record.

    Sets each flag to False instead of removing the entry. `StateHelper:
    LoadFactionExpulsion` iterates `pairs(factionExpulsion)` and sends only the
    entries it finds, so a deleted entry transmits nothing at all and the client
    goes on believing it is expelled — the same trap as blanking credentials
    rather than resetting them.

    Only correct for a player who is OFFLINE. A logged-in player's expulsion
    state lives in memory and would overwrite this file on the next save; route
    those through `queue_command` instead so the change goes via the live
    player object.
    """
    path = _player_dir(data_root) / f"{name}.json"
    record = _load(path)
    if record is None:
        return False

    table = _expulsion_table(record)
    if table:
        record["factionExpulsion"] = {faction_id: False for faction_id in table}
        _save(path, record)

    check = _load(path) or {}
    return not any(
        state is True for state in _expulsion_table(check).values()
    )


def reset_password(data_root: Path, name: str, new_password: str) -> bool:
    """Write a real salt+hash. Refuses to blank credentials — see module docstring."""
    if not new_password:
        raise ValueError("a password is required; clearing credentials crashes the server")
    path = _player_dir(data_root) / f"{name}.json"
    record = _load(path)
    if record is None:
        return False
    salt = "".join(secrets.choice(SALT_ALPHABET) for _ in range(64))
    login = record.get("login")
    if not isinstance(login, dict):
        login = {}
    login["name"] = login.get("name", name)
    login["passwordSalt"] = salt
    login["passwordHash"] = hashlib.sha256((new_password + salt).encode("utf-8")).hexdigest()
    record["login"] = login
    _save(path, record)

    check = _load(path) or {}
    verify = check.get("login", {})
    expected = hashlib.sha256(
        (new_password + verify.get("passwordSalt", "")).encode("utf-8")
    ).hexdigest()
    return verify.get("passwordHash") == expected


def live_players(data_root: Path) -> list[dict]:
    """Currently connected players, from the roster the server Lua writes."""
    path = data_root / "live_players.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    players = payload.get("players")
    return players if isinstance(players, list) else []


def queue_command(data_root: Path, command: dict) -> None:
    """Hand one action to the roster Lua's poll timer (~1s latency)."""
    path = data_root / "host_commands.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(command), encoding="utf-8")
    staging.replace(path)
