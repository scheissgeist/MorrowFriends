"""Find and validate a Morrowind GOTY install."""

from __future__ import annotations

import json
import re
import winreg
from dataclasses import dataclass
from pathlib import Path

from .paths import GOTY_ARCHIVES, GOTY_MASTERS, settings_path

STEAM_APP_ID = "22320"


@dataclass
class MorrowindInstall:
    root: Path
    data_files: Path
    source: str  # steam | gog | remembered | manual

    @property
    def display(self) -> str:
        return str(self.root)


@dataclass
class ValidationResult:
    ok: bool
    install: MorrowindInstall | None
    missing: list[str]
    message: str


def _norm(path: Path) -> Path:
    return path.resolve()


def data_files_dir(root: Path) -> Path | None:
    """Return Data Files directory if it looks like a Morrowind install."""
    candidates = [root / "Data Files", root]
    for cand in candidates:
        if (cand / "Morrowind.esm").is_file():
            return cand
    return None


def validate_install(root: Path, source: str = "manual") -> ValidationResult:
    root = Path(root)
    if not root.exists():
        return ValidationResult(False, None, [], f"Path does not exist: {root}")

    data = data_files_dir(root)
    if data is None:
        # Maybe they picked Data Files itself
        if (root / "Morrowind.esm").is_file():
            data = root
            # Prefer parent as root if named Data Files
            game_root = root.parent if root.name.lower() == "data files" else root
        else:
            return ValidationResult(
                False,
                None,
                ["Morrowind.esm"],
                "Could not find Morrowind.esm. Pick the game folder or its Data Files folder.",
            )
    else:
        game_root = root if (root / "Data Files").is_dir() or data != root else root
        if data.name.lower() == "data files":
            game_root = data.parent

    missing: list[str] = []
    for name in GOTY_MASTERS + GOTY_ARCHIVES:
        if not (data / name).is_file():
            missing.append(name)

    install = MorrowindInstall(root=_norm(game_root), data_files=_norm(data), source=source)
    if missing:
        return ValidationResult(
            False,
            install,
            missing,
            "Morrowind found, but GOTY expansions are incomplete. "
            "Need Tribunal + Bloodmoon (Steam GOTY / expansions).\n"
            f"Missing: {', '.join(missing)}",
        )
    return ValidationResult(True, install, [], f"Valid GOTY install ({source})")


def load_remembered_path() -> Path | None:
    path = settings_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("morrowind_path")
        if raw:
            return Path(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return None


def save_remembered_path(morrowind_root: Path) -> None:
    path = settings_path()
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    data["morrowind_path"] = str(morrowind_root)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_reg_str(hive: int, key: str, value: str) -> str | None:
    try:
        with winreg.OpenKey(hive, key) as handle:
            data, _ = winreg.QueryValueEx(handle, value)
            if isinstance(data, str) and data:
                return data
    except OSError:
        return None
    return None


def _steam_install_path() -> Path | None:
    for hive, key in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ):
        raw = _read_reg_str(hive, key, "SteamPath") or _read_reg_str(hive, key, "InstallPath")
        if raw:
            return Path(raw)
    defaults = [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"C:\Program Files\Steam"),
    ]
    for d in defaults:
        if d.is_dir():
            return d
    return None


def _parse_library_folders(vdf: Path) -> list[Path]:
    if not vdf.is_file():
        return []
    text = vdf.read_text(encoding="utf-8", errors="ignore")
    paths = re.findall(r'"path"\s+"([^"]+)"', text)
    out: list[Path] = []
    for p in paths:
        out.append(Path(p.replace("\\\\", "\\")))
    # Older format: "1" "D:\\SteamLibrary"
    for m in re.finditer(r'"\d+"\s+"([A-Za-z]:\\\\[^"]+)"', text):
        out.append(Path(m.group(1).replace("\\\\", "\\")))
    return out


def find_steam_morrowind() -> MorrowindInstall | None:
    steam = _steam_install_path()
    if steam is None:
        return None

    libraries = [steam]
    libraries.extend(_parse_library_folders(steam / "steamapps" / "libraryfolders.vdf"))

    seen: set[Path] = set()
    for lib in libraries:
        lib = Path(lib)
        if lib in seen:
            continue
        seen.add(lib)
        common = lib / "steamapps" / "common" / "Morrowind"
        manifest = lib / "steamapps" / f"appmanifest_{STEAM_APP_ID}.acf"
        if common.is_dir() and data_files_dir(common):
            return MorrowindInstall(_norm(common), _norm(data_files_dir(common)), "steam")  # type: ignore[arg-type]
        if manifest.is_file():
            # Still try common even if somehow partial
            if common.is_dir() and data_files_dir(common):
                return MorrowindInstall(_norm(common), _norm(data_files_dir(common)), "steam")  # type: ignore[arg-type]
    return None


def find_gog_morrowind() -> MorrowindInstall | None:
    candidates: list[Path] = []
    for hive, key, value in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games\1440406123", "path"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games\1440406123", "path"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games\1435827232", "path"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games\1435827232", "path"),
    ):
        raw = _read_reg_str(hive, key, value)
        if raw:
            candidates.append(Path(raw))

    for base in (
        Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Morrowind"),
        Path(r"C:\GOG Games\Morrowind"),
        Path(r"D:\GOG Games\Morrowind"),
    ):
        candidates.append(base)

    for cand in candidates:
        data = data_files_dir(cand)
        if data is not None:
            root = data.parent if data.name.lower() == "data files" else cand
            return MorrowindInstall(_norm(root), _norm(data), "gog")
    return None


def detect_morrowind() -> ValidationResult:
    """Steam → GOG → remembered → fail (UI will offer browse)."""
    steam = find_steam_morrowind()
    if steam:
        result = validate_install(steam.root, source="steam")
        if result.ok:
            return result

    gog = find_gog_morrowind()
    if gog:
        result = validate_install(gog.root, source="gog")
        if result.ok:
            return result

    remembered = load_remembered_path()
    if remembered:
        result = validate_install(remembered, source="remembered")
        if result.ok:
            return result

    # Return best partial for messaging
    for candidate in (steam, gog):
        if candidate:
            return validate_install(candidate.root, source=candidate.source)

    return ValidationResult(
        False,
        None,
        [],
        "No Morrowind install found. Use Browse to pick your game folder "
        "(Steam/GOG GOTY with Tribunal + Bloodmoon).",
    )
