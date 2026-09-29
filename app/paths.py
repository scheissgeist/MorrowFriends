"""App data locations and constants."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "MorrowFriends"
LEGACY_APP_NAME = "MorrowindFriends"
APP_VERSION = "0.7.5"

# Pinned multiplayer engine — host and guests must match.
TES3MP_VERSION = "0.8.1"
TES3MP_DOWNLOAD_URL = (
    "https://github.com/TES3MP/TES3MP/releases/download/"
    "tes3mp-0.8.1/tes3mp.Win64.release.0.8.1.zip"
)
TES3MP_ZIP_NAME = "tes3mp.Win64.release.0.8.1.zip"
# Verified against a fresh download of the upstream GitHub release asset.
TES3MP_ZIP_SHA256 = "72d35d574689e698196855c80e27bf79a86a591c2a7d42dddd03de0c597e2bad"
VC_RUNTIME_DOWNLOAD_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
VC_RUNTIME_INSTALLER_NAME = "vc_redist.x64.exe"
DEFAULT_PORT = 25565

# Vanilla GOTY content for Quick Co-op.
GOTY_MASTERS = ("Morrowind.esm", "Tribunal.esm", "Bloodmoon.esm")
GOTY_ARCHIVES = ("Morrowind.bsa", "Tribunal.bsa", "Bloodmoon.bsa")


def local_app_data() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local"))
    path = base / APP_NAME
    legacy = base / LEGACY_APP_NAME
    if not path.exists() and legacy.exists():
        try:
            legacy.rename(path)
        except OSError:
            # Locked / cross-device — keep using legacy folder
            return legacy
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return local_app_data() / "settings.json"


def tes3mp_dir() -> Path:
    path = local_app_data() / "tes3mp" / TES3MP_VERSION
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir() -> Path:
    path = local_app_data() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Isolated OpenMW/TES3MP config — does not touch Documents\\My Games\\OpenMW."""
    path = local_app_data() / "config"
    path.mkdir(parents=True, exist_ok=True)
    return path


def server_state_dir() -> Path:
    path = local_app_data() / "server"
    path.mkdir(parents=True, exist_ok=True)
    return path
