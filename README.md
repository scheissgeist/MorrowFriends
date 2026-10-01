# MorrowFriends

MorrowFriends is a Windows launcher for playing **The Elder Scrolls III:
Morrowind** cooperatively. It finds an existing Morrowind GOTY installation,
downloads the matching TES3MP client, joins the MorrowFriends server, and keeps
optional proximity voice in the launcher window.

## Download

Download the latest Windows ZIP from
[GitHub Releases](https://github.com/scheissgeist/MorrowFriends/releases/latest).
Do not download the automatically generated "Source code" archives unless you
intend to run or build the launcher yourself.

## Requirements

- Windows 10 or 11
- A legally obtained installation of Morrowind GOTY, including Tribunal and
  Bloodmoon
- An internet connection

MorrowFriends does **not** include or redistribute Bethesda game files.

## Playing

1. Download and extract `MorrowFriends-v0.7.5-Windows.zip`.
2. Open the extracted `MorrowFriends` folder and run `MorrowFriends.bat`. Keep
   the whole folder together.
3. Enter the account name you already use in TES3MP, or leave it blank while
   creating your first character.
4. Press **Play**.

The ZIP contains no MorrowFriends-built executable. `MorrowFriends.bat` starts
the bundled copy of Python (`runtime\pythonw.exe`, signed by the Python
Software Foundation) on the launcher's source in `app\`, which you can read.
Nothing is installed. Windows may still ask for confirmation the first time you
run a downloaded `.bat`. Each release publishes a SHA-256 checksum so the
downloaded ZIP can be verified.

## What the launcher does

- Detects Steam, GOG, or manually selected Morrowind GOTY files.
- Downloads TES3MP 0.8.1 from its official GitHub release and verifies the
  archive against a pinned SHA-256 digest.
- Connects to the public MorrowFriends server.
- Opens optional positional voice and push-to-talk.
- Provides a nearby-player strip with `/goto` shortcuts.

Quest progress, faction ranks, and dialogue topics are shared. Crime and
character inventories remain personal.

## Privacy and online play

This is an online multiplayer launcher. Read [PRIVACY.md](PRIVACY.md) before
connecting. The launcher has no advertising or analytics SDK. The game and
voice services necessarily receive connection, character, and live positional
information while you use them.

## Run from source

```powershell
git clone https://github.com/scheissgeist/MorrowFriends.git
cd MorrowFriends
python -m pip install -r requirements.txt
python run.py
```

## Build

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
powershell -File packaging/build_portable.ps1 -Python .venv\Scripts\python.exe
powershell -File packaging/defender_gate.ps1 -Path dist\portable\MorrowFriends\runtime\pythonw.exe
```

`build_portable.ps1` downloads python.org's embeddable Python (matching the
venv's version), adds tkinter from the local Python install, installs the
runtime dependencies beside it, and copies the launcher source. It writes
`dist/portable/MorrowFriends/` and a versioned ZIP to the current user's
Desktop, and fails if any `.exe` in the release lacks a valid signature.

Releases up to v0.7.4 were a PyInstaller executable. Antivirus engines,
including Microsoft Defender, flag fresh unsigned PyInstaller executables, so
that packaging (`build.ps1`, `morrowfriends.spec`) is no longer used for
releases. `defender_gate.ps1` checks files against the local Microsoft Defender
the way a browser download is checked.

## Support and security

Use GitHub Issues for reproducible bugs. Report security problems privately as
described in [SECURITY.md](SECURITY.md).

MorrowFriends is an independent community project. It is not affiliated with
or endorsed by Bethesda Softworks, ZeniMax Media, TES3MP, or Microsoft.

## License

MorrowFriends source code is licensed under the [MIT License](LICENSE).
Third-party components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
