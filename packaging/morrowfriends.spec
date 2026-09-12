# -*- mode: python ; coding: utf-8 -*-
# Build: powershell -File packaging/build.ps1

from pathlib import Path

block_cipher = None
SPEC_DIR = Path(SPECPATH)
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MorrowFriends",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_arg,
)
