"""Read and write TES3MP co-op rules in server/scripts/config.lua.

Server-side port of app/coop.py so the web panel can change the same settings
the desktop launcher writes, without the launcher running.

Every write is verified by reading the value back — a regex that matches nothing
returns the input unchanged and would otherwise report success while the setting
never changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    help: str


# Ordered for display. `shareBounty` is first because it is the one with a
# consequence people ask about: with it FALSE, a player who commits a crime is
# wanted alone — guards hunt them, not the whole party. Verified in
# CoreScripts eventHandler.lua OnPlayerBounty: the share branch loops every
# player calling SetBounty+SendBounty; otherwise only the offender's bounty is
# saved.
RULES: tuple[Rule, ...] = (
    Rule("shareBounty", "Share crime bounty",
         "ON: everyone becomes wanted when one player commits a crime. "
         "OFF: only the criminal is hunted by guards."),
    Rule("shareJournal", "Share quest journal",
         "Quest progress advances for every player at once."),
    Rule("shareFactionRanks", "Share faction ranks",
         "Guild and faction promotions apply to everyone."),
    Rule("shareFactionReputation", "Share faction reputation",
         "Standing within a faction is shared."),
    Rule("shareFactionExpulsion", "Share faction expulsion",
         "ON: if one player is expelled, all are."),
    Rule("shareTopics", "Share dialogue topics",
         "Topics learned by one player are known to all."),
    Rule("shareReputation", "Share general reputation",
         "Overall reputation is shared."),
    Rule("shareMapExploration", "Share map exploration",
         "ON: the map reveals for everyone as any player explores."),
    Rule("bountyResetOnDeath", "Clear bounty on death",
         "Dying wipes the player's bounty."),
    Rule("bountyDeathPenalty", "Jail time on death",
         "Dying with a bounty sends the player to jail."),
)

RULE_KEYS = tuple(rule.key for rule in RULES)


def read_rules(config_path: Path) -> dict[str, bool]:
    """Return the current value of every known rule. Missing keys are omitted."""
    if not config_path.is_file():
        return {}
    text = config_path.read_text(encoding="utf-8")
    values: dict[str, bool] = {}
    for key in RULE_KEYS:
        match = re.search(rf"config\.{re.escape(key)}\s*=\s*(true|false)", text)
        if match:
            values[key] = match.group(1) == "true"
    return values


def set_rule(config_path: Path, key: str, value: bool) -> bool:
    """Set one rule and CONFIRM it by reading the file back.

    Returns True only when the file now holds the requested value.
    """
    if key not in RULE_KEYS:
        raise ValueError(f"unknown rule: {key}")
    if not config_path.is_file():
        raise FileNotFoundError(config_path)

    text = config_path.read_text(encoding="utf-8")
    lua_bool = "true" if value else "false"
    pattern = rf"(config\.{re.escape(key)}\s*=\s*)(true|false)"
    updated, count = re.subn(pattern, rf"\g<1>{lua_bool}", text, count=1)
    if count == 0:
        # Key absent entirely — append rather than silently doing nothing.
        updated = text.rstrip() + f"\nconfig.{key} = {lua_bool}\n"

    staging = config_path.with_name(config_path.name + ".tmp")
    staging.write_text(updated, encoding="utf-8")
    staging.replace(config_path)

    # Read back. A regex that matched nothing would otherwise report success.
    return read_rules(config_path).get(key) is value
