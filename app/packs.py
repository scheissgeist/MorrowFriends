"""Content packs for multiplayer (vanilla GOTY, Tamriel Rebuilt, …)."""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from pathlib import Path

from .detect import MorrowindInstall
from .paths import GOTY_ARCHIVES, GOTY_MASTERS

# English + Russian GOTY checksums accepted by default TES3MP servers.
GOTY_CHECKSUMS: dict[str, list[str]] = {
    "Morrowind.esm": ["0x7B6AF5B9", "0x34282D67"],
    "Tribunal.esm": ["0xF481F334", "0x211329EF"],
    "Bloodmoon.esm": ["0x43DD2132", "0x9EB62F26"],
}


@dataclass(frozen=True)
class PackDef:
    id: str
    label: str
    # Extra content after GOTY masters (filename only, in Data Files)
    extra_content: tuple[str, ...]
    # Extra BSA archives if present
    extra_archives: tuple[str, ...] = ()


VANILLA = PackDef(
    id="vanilla",
    label="Quick Co-op (vanilla GOTY)",
    extra_content=(),
)

TAMRIEL_REBUILT = PackDef(
    id="tamriel_rebuilt",
    label="Tamriel Rebuilt",
    extra_content=(
        "Tamriel_Data.esm",
        "TR_Mainland.esm",
        "TR_Factions.esp",
    ),
    extra_archives=(
        "Tamriel_Data.bsa",
        "TR_Data.bsa",
    ),
)

PACKS: dict[str, PackDef] = {
    VANILLA.id: VANILLA,
    TAMRIEL_REBUILT.id: TAMRIEL_REBUILT,
}


def get_pack(pack_id: str) -> PackDef:
    return PACKS.get(pack_id, VANILLA)


def content_list(pack: PackDef) -> list[str]:
    return list(GOTY_MASTERS) + list(pack.extra_content)


def crc32_hex(path: Path) -> str:
    """TES3MP-style CRC32 (zlib, unsigned hex with 0x prefix)."""
    crc = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return f"0x{(crc & 0xFFFFFFFF):08X}"


def pack_status(install: MorrowindInstall, pack: PackDef) -> tuple[bool, str, list[str]]:
    """Return (ok, message, missing_required). Optional extras may be skipped."""
    if pack.id == VANILLA.id:
        return True, "Vanilla GOTY", []

    missing: list[str] = []
    # Require core TR masters; factions esp is nice-to-have but include if we list it
    required = ("Tamriel_Data.esm", "TR_Mainland.esm")
    for name in required:
        if not (install.data_files / name).is_file():
            missing.append(name)

    if missing:
        return (
            False,
            "Tamriel Rebuilt files not found in Data Files. "
            "Install Tamriel Data + TR Mainland (or pick vanilla).",
            list(missing),
        )

    present_extra = [n for n in pack.extra_content if (install.data_files / n).is_file()]
    return True, f"TR ready ({', '.join(present_extra)})", []


def active_content(install: MorrowindInstall, pack: PackDef) -> list[str]:
    """GOTY + pack extras that actually exist on disk."""
    files = list(GOTY_MASTERS)
    for name in pack.extra_content:
        if (install.data_files / name).is_file():
            files.append(name)
    return files


def active_archives(install: MorrowindInstall, pack: PackDef) -> list[str]:
    archives = list(GOTY_ARCHIVES)
    for name in pack.extra_archives:
        if (install.data_files / name).is_file():
            archives.append(name)
    return archives


def build_required_data_files(install: MorrowindInstall, pack: PackDef) -> list[dict]:
    """Build requiredDataFiles.json structure with checksums."""
    entries: list[dict] = []
    for name in active_content(install, pack):
        path = install.data_files / name
        if name in GOTY_CHECKSUMS:
            checksums = list(GOTY_CHECKSUMS[name])
            # Also accept whatever is on disk (GOG / odd editions)
            disk = crc32_hex(path)
            if disk not in checksums:
                checksums.append(disk)
        else:
            checksums = [crc32_hex(path)]
        entries.append({name: checksums})
    return entries


def write_required_data_files(install: MorrowindInstall, pack: PackDef, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = build_required_data_files(install, pack)
    # JSONC-ish header not valid JSON — write pure JSON array (TES3MP accepts comments
    # in some builds; stick to pure JSON for safety)
    text = json.dumps(payload, indent=4) + "\n"
    dest.write_text(text, encoding="utf-8")
    return dest
