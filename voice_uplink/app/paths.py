"""Stub: the uplink supplies explicit data paths, never these defaults."""
from pathlib import Path
import os


def tes3mp_dir() -> Path:
    return Path(os.environ.get("TES3MP_DATA", "/server/data/data"))
