# -*- mode: python ; coding: utf-8 -*-
# Build: powershell -File packaging/build.ps1

import os
import re
from pathlib import Path

from PyInstaller.utils.win32 import versioninfo as vi

block_cipher = None
SPEC_DIR = Path(SPECPATH)
# MF_ONEDIR=1 builds a folder (MorrowFriends/MorrowFriends.exe + _internal/)
# instead of one self-extracting exe. One-file PyInstaller exes unpack a Python
# runtime into %TEMP% at launch, which is the dropper-like shape AV ML models flag.
ONEDIR = os.environ.get("MF_ONEDIR") == "1"

# Windows version resource, single-sourced from app/paths.py APP_VERSION.
# An unsigned exe with no publisher/product metadata scores worse with
# Defender's cloud ML (v0.7.4 had none and hit Trojan:Win32/Wacatac.C!ml).
_ver_src = (SPEC_DIR.parent / "app" / "paths.py").read_text(encoding="utf-8")
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', _ver_src, re.M).group(1)
_vt = tuple((int(p) for p in (APP_VERSION.split(".") + ["0", "0", "0"])[:4]))
VERSION_INFO = vi.VSVersionInfo(
    ffi=vi.FixedFileInfo(filevers=_vt, prodvers=_vt, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        vi.StringFileInfo([
            vi.StringTable("040904B0", [
                vi.StringStruct("CompanyName", "MorrowFriends contributors"),
                vi.StringStruct("FileDescription", "MorrowFriends - TES3MP co-op launcher for Morrowind"),
                vi.StringStruct("FileVersion", APP_VERSION),
                vi.StringStruct("InternalName", "MorrowFriends"),
                vi.StringStruct("LegalCopyright", "Copyright (c) 2026 MorrowFriends contributors. MIT License."),
                vi.StringStruct("OriginalFilename", "MorrowFriends.exe"),
                vi.StringStruct("ProductName", "MorrowFriends"),
                vi.StringStruct("ProductVersion", APP_VERSION),
            ])
        ]),
        vi.VarFileInfo([vi.VarStruct("Translation", [0x0409, 1200])]),
    ],
)
ICON = SPEC_DIR / "morrowfriends.ico"
PNG = SPEC_DIR / "morrowfriends.png"
icon_arg = str(ICON) if ICON.is_file() else None
datas = []
if PNG.is_file():
    datas.append((str(PNG), "."))
if ICON.is_file():
    datas.append((str(ICON), "."))
ROSTER = SPEC_DIR / "tes3mp_custom_scripts" / "morrowfriends_roster.lua"
if ROSTER.is_file():
    datas.append((str(ROSTER), "."))
PLAYER_TP = SPEC_DIR / "tes3mp_custom_scripts" / "morrowfriends_player_teleport.lua"
if PLAYER_TP.is_file():
    datas.append((str(PLAYER_TP), "."))
FRIENDLY_FIRE = SPEC_DIR / "tes3mp_custom_scripts" / "morrowfriends_friendly_fire.lua"
if FRIENDLY_FIRE.is_file():
    datas.append((str(FRIENDLY_FIRE), "."))

# app/voice_embed.py renders voice INSIDE the launcher window using the WebView2
# assemblies that ship inside pywebview. PyInstaller collects the python
# packages but not that DLL tree, and voice_embed looks for it at
# sys._MEIPASS/webview/lib, so place it there explicitly. Without this the
# embedded voice panel silently falls back to a second window in the built app
# while working perfectly from source.
try:
    import webview as _webview

    _WEBVIEW_LIB = Path(_webview.__file__).parent / "lib"
    if _WEBVIEW_LIB.is_dir():
        datas.append((str(_WEBVIEW_LIB), "webview/lib"))
except Exception:
    pass

a = Analysis(
    [str(SPEC_DIR.parent / "run.py")],
    pathex=[str(SPEC_DIR.parent)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "customtkinter",
        "websockets.sync.client",
        "webview",
        "webview.platforms.edgechromium",
        # voice_embed drives WebView2 through pythonnet directly.
        "clr",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy", "pandas", "scipy", "matplotlib", "pygame", "torch", "cv2"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

_exe_opts = dict(
    name="MorrowFriends",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX was never installed on the build machine, so upx=True was a no-op;
    # keep it off explicitly, packed exes are an AV red flag.
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
    version=VERSION_INFO,
)

if ONEDIR:
    # MF_APPEND_PKG=0 writes MorrowFriends.pkg beside the exe instead of appending
    # it as a PE overlay, leaving the exe as bare bootloader + resources.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              append_pkg=os.environ.get("MF_APPEND_PKG", "1") != "0", **_exe_opts)
    coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="MorrowFriends")
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [], runtime_tmpdir=None, **_exe_opts)
