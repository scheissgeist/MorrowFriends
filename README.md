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

1. Download and extract `MorrowFriends-v0.7.4-Windows.zip`.
2. Run `MorrowFriends.exe`.
3. Enter the account name you already use in TES3MP, or leave it blank while
   creating your first character.
4. Press **Play**.

The current build is unsigned, so Windows may show a SmartScreen warning. Each
release publishes a SHA-256 checksum so the downloaded ZIP can be verified.

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
powershell -File packaging/build.ps1 -Python .venv\Scripts\python.exe
```

The build writes `dist/MorrowFriends.exe` and a versioned ZIP to the current
user's Desktop. Signing is used automatically when a local signing certificate
is configured through `MORROWFRIENDS_PFX`.

## Support and security

Use GitHub Issues for reproducible bugs. Report security problems privately as
described in [SECURITY.md](SECURITY.md).

MorrowFriends is an independent community project. It is not affiliated with
or endorsed by Bethesda Softworks, ZeniMax Media, TES3MP, or Microsoft.

## License

MorrowFriends source code is licensed under the [MIT License](LICENSE).
Third-party components retain their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
