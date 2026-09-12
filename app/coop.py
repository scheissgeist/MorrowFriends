"""Co-op rules: shared journal / story progress (TES3MP CoreScripts)."""

from __future__ import annotations

import re
from pathlib import Path

# Friends co-op: everyone advances the story together (TES3MP defaults we care about).
COOP_RULES: dict[str, bool] = {
    "shareJournal": True,
    "shareFactionRanks": True,
    "shareFactionExpulsion": False,
    "shareFactionReputation": True,
    "shareTopics": True,
    "shareBounty": False,
    "shareReputation": True,
    "shareMapExploration": False,
    "shareVideos": True,
}


def apply_coop_rules(tes3mp_root: Path) -> Path:
    """
    Force shared-story settings in server/scripts/config.lua.
    Idempotent — safe to run on every Host.
    """
    cfg_path = tes3mp_root / "server" / "scripts" / "config.lua"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Missing CoreScripts config: {cfg_path}")

    text = cfg_path.read_text(encoding="utf-8")
    original = text

    for key, value in COOP_RULES.items():
        lua_bool = "true" if value else "false"
        pattern = rf"(config\.{re.escape(key)}\s*=\s*)(true|false)"
        replacement = rf"\g<1>{lua_bool}"
        new_text, n = re.subn(pattern, replacement, text, count=1)
        if n == 0:
            # Append near other share* settings if somehow missing
            anchor = "config.shareJournal"
            if anchor in text:
                text = text.replace(
                    f"config.shareJournal = {'true' if COOP_RULES['shareJournal'] else 'false'}",
                    f"config.shareJournal = {'true' if COOP_RULES['shareJournal'] else 'false'}",
                    1,
                )
            # If key truly missing, append at end of file
            if f"config.{key}" not in text:
                text = text.rstrip() + f"\nconfig.{key} = {lua_bool}\n"
        else:
            text = new_text

    if text != original:
        cfg_path.write_text(text, encoding="utf-8")
    return cfg_path


def coop_summary() -> str:
    return "Shared story — journal, factions, and topics advance for everyone"
