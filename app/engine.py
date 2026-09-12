"""Ensure TES3MP is installed and launch client/server."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

from .config import (
    ensure_native_openmw_profile,
    ensure_mp_profile,
    read_host_command_result,
    read_live_position_snapshot,
    read_live_roster,
    sync_engine_configs,
    verify_client_destination,
    write_client_cfg,
    write_host_command,
    write_server_cfg,
)
from .coop import apply_coop_rules, coop_summary
from .detect import MorrowindInstall
from .invite import Invite
from .packs import VANILLA, PackDef, get_pack, pack_status
from .paths import (
    DEFAULT_PORT,
    TES3MP_DOWNLOAD_URL,
    TES3MP_VERSION,
    TES3MP_ZIP_NAME,
    TES3MP_ZIP_SHA256,
    VC_RUNTIME_DOWNLOAD_URL,
    VC_RUNTIME_INSTALLER_NAME,
    downloads_dir,
    tes3mp_dir,
)
from .voice import PositionSnapshot, parse_position_snapshot

ProgressCb = Callable[[str], None]

REQUIRED_TES3MP_PATHS = (
    "tes3mp.exe",
    "tes3mp-server.exe",
    "libcurl.dll",
    "lua51.dll",
    "server/scripts/serverCore.lua",
    "resources/vfs",
)

VC_RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def _log(cb: ProgressCb | None, msg: str) -> None:
    if cb:
        cb(msg)


def vc_runtime_ready(
    *, system_root: Path | None = None, engine_root: Path | None = None
) -> bool:
    """Return whether the x64 MSVC libraries imported by TES3MP are available."""
    if os.name != "nt" and system_root is None and engine_root is None:
        return True
    system_root = system_root or Path(os.environ.get("SystemRoot", r"C:\Windows"))
    engine_root = engine_root or tes3mp_dir()
    locations = (engine_root, system_root / "System32")
    return all(any((location / dll).is_file() for location in locations) for dll in VC_RUNTIME_DLLS)


def _valid_microsoft_signature(path: Path) -> bool:
    """Verify the downloaded prerequisite is Authenticode-signed by Microsoft."""
    if os.name != "nt" or not path.is_file():
        return False
    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
        "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match "
        "'(^|, )O=Microsoft Corporation(,|$)') { exit 0 }; exit 1"
    )
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def install_vc_runtime(cb: ProgressCb | None = None) -> bool:
    """Install Microsoft's current x64 VC++ runtime. Return whether Windows must restart."""
    if vc_runtime_ready():
        _log(cb, "Microsoft C++ runtime is already installed.")
        return False
    if os.name != "nt":
        raise RuntimeError("The Microsoft C++ runtime installer is only available on Windows.")

    installer = downloads_dir() / VC_RUNTIME_INSTALLER_NAME
    partial = installer.with_suffix(installer.suffix + ".part")
    partial.unlink(missing_ok=True)
    _log(cb, "Downloading the required Microsoft C++ runtime…")

    def _hook(block: int, block_size: int, total: int) -> None:
        if total <= 0:
            return
        done = min(block * block_size, total)
        pct = int(done * 100 / total)
        if block % 32 == 0 or done >= total:
            _log(cb, f"Downloading Microsoft C++ runtime… {pct}%")

    try:
        urlretrieve(VC_RUNTIME_DOWNLOAD_URL, partial, reporthook=_hook)
        if not _valid_microsoft_signature(partial):
            raise RuntimeError(
                "The Microsoft C++ runtime download could not be verified. Nothing was installed."
            )
        partial.replace(installer)
    finally:
        partial.unlink(missing_ok=True)

    _log(cb, "Download verified. Approve the Windows prompt to install the C++ runtime…")
    try:
        result = subprocess.run(
            [str(installer), "/install", "/passive", "/norestart"],
            cwd=str(installer.parent),
            timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The Microsoft C++ runtime installer did not finish.") from exc

    restart_required = result.returncode == 3010
    if result.returncode not in (0, 1638, 3010):
        raise RuntimeError(
            f"Microsoft C++ runtime installer exited with code {result.returncode}."
        )
    if not vc_runtime_ready() and not restart_required:
        raise RuntimeError(
            "The installer finished, but the required C++ files are still missing. Restart Windows and try again."
        )
    _log(
        cb,
        "Microsoft C++ runtime installed; restart Windows before playing."
        if restart_required
        else "Microsoft C++ runtime installed and verified.",
    )
    return restart_required


def find_local_tes3mp_candidates() -> list[Path]:
    """Known places the user may already have TES3MP."""
    candidates: list[Path] = []
    steam_mw = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Morrowind\OpenMW 0.48.0")
    if steam_mw.is_dir():
        candidates.append(steam_mw)
    pinned = tes3mp_dir()
    if pinned.is_dir():
        candidates.insert(0, pinned)
    return candidates


def tes3mp_ready(root: Path | None = None) -> Path | None:
    root = root or tes3mp_dir()
    if all((root / relative).exists() for relative in REQUIRED_TES3MP_PATHS):
        return root
    return None


def live_roster() -> list[dict]:
    """Connected players (pid + in-game name) written live by the roster hook script."""
    return read_live_roster(tes3mp_dir())


def live_voice_snapshot() -> PositionSnapshot:
    """Latest position feed with file age translated to monotonic time."""
    payload = read_live_position_snapshot(tes3mp_dir())
    modified_at = payload.pop("_fileMtime", None)
    if modified_at is None:
        observed_at = 0.0
    else:
        age = max(0.0, time.time() - float(modified_at))
        observed_at = time.monotonic() - age
    return parse_position_snapshot(payload, observed_at=observed_at)


def kick_player(player_name: str) -> None:
    write_host_command(tes3mp_dir(), {"action": "kick", "target": player_name})


def teleport_player_to_host(player_name: str, host_name: str) -> None:
    write_host_command(
        tes3mp_dir(), {"action": "teleport_to_host", "target": player_name, "host": host_name}
    )


def teleport_host_to_player(player_name: str, host_name: str) -> None:
    write_host_command(
        tes3mp_dir(), {"action": "teleport_host_to", "target": player_name, "host": host_name}
    )


def broadcast_message(message: str) -> None:
    write_host_command(tes3mp_dir(), {"action": "broadcast", "message": message})


def give_gold(player_name: str, amount: int) -> None:
    write_host_command(tes3mp_dir(), {"action": "give_gold", "target": player_name, "amount": amount})


def grant_host_console(player_name: str) -> None:
    """Promote the selected local host to owner and enable their in-game console."""
    write_host_command(tes3mp_dir(), {"action": "grant_host_owner", "target": player_name})


def revoke_host_console(player_name: str) -> None:
    """Demote a player to a normal account and take away their in-game console."""
    write_host_command(tes3mp_dir(), {"action": "revoke_host_owner", "target": player_name})


def save_server_state(timeout: float = 5.0, cb: ProgressCb | None = None) -> None:
    """Ask the Lua bridge to persist all live players/world data and wait for proof."""
    root = tes3mp_dir()
    request_id = uuid.uuid4().hex
    _log(cb, "Saving every connected character and the shared worldâ€¦")
    write_host_command(root, {"action": "save_all", "requestId": request_id})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = read_host_command_result(root)
        if result.get("requestId") == request_id:
            if not result.get("ok"):
                detail = result.get("error") or "TES3MP reported an unknown save error."
                raise RuntimeError(f"Server save failed: {detail}")
            count = int(result.get("detail") or 0)
            label = "character" if count == 1 else "characters"
            _log(cb, f"Save confirmed for {count} connected {label} and the shared world.")
            return
        time.sleep(0.1)
    raise RuntimeError(
        "The server did not confirm the save, so it was left running. "
        "Wait a moment and press Stop again."
    )


def _extract_zip(zip_path: Path, dest: Path, cb: ProgressCb | None) -> None:
    _log(cb, "Extracting TES3MP…")
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        # Zip may contain a single top-level folder or files at root
        names = zf.namelist()
        if not names:
            raise RuntimeError("TES3MP zip was empty.")
        top_dirs = {n.split("/")[0] for n in names if n and not n.startswith("__")}
        # A unique sibling folder prevents simultaneous or interrupted repairs
        # from trampling one another.
        staging = Path(tempfile.mkdtemp(prefix=f".extract-{TES3MP_VERSION}-", dir=dest.parent))
        zf.extractall(staging)

    # If staging has one directory containing tes3mp.exe, use that
    direct = staging / "tes3mp.exe"
    if direct.is_file():
        source = staging
    else:
        subdirs = [p for p in staging.iterdir() if p.is_dir()]
        source = None
        for sub in subdirs:
            if (sub / "tes3mp.exe").is_file():
                source = sub
                break
        if source is None:
            # search deeper
            for exe in staging.rglob("tes3mp.exe"):
                source = exe.parent
                break
        if source is None:
            raise RuntimeError("Could not find tes3mp.exe inside the downloaded zip.")

    try:
        # Merge the verified engine over the existing install. In particular,
        # never delete server/data: that directory contains the host's saves.
        dest.mkdir(parents=True, exist_ok=True)
        for item in source.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # silence unused
    _ = top_dirs


def _valid_tes3mp_zip(zip_path: Path, expected_sha256: str | None = None) -> bool:
    try:
        if expected_sha256:
            digest = hashlib.sha256()
            with zip_path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            if not hmac.compare_digest(digest.hexdigest(), expected_sha256.lower()):
                return False
        with zipfile.ZipFile(zip_path, "r") as archive:
            if archive.testzip() is not None:
                return False
            names = [name.replace("\\", "/") for name in archive.namelist()]
            return any(name.endswith("/tes3mp.exe") or name == "tes3mp.exe" for name in names)
    except (OSError, zipfile.BadZipFile):
        return False


def download_tes3mp(cb: ProgressCb | None = None, *, force: bool = False) -> Path:
    dest = tes3mp_dir()
    ready = tes3mp_ready(dest)
    if ready and not force:
        _log(cb, f"TES3MP {TES3MP_VERSION} already installed.")
        return ready

    zip_path = downloads_dir() / TES3MP_ZIP_NAME
    if force or not _valid_tes3mp_zip(zip_path, TES3MP_ZIP_SHA256):
        _log(cb, f"Downloading TES3MP {TES3MP_VERSION} (~62 MB)…")

        def _hook(block: int, block_size: int, total: int) -> None:
            if total <= 0:
                return
            done = min(block * block_size, total)
            pct = int(done * 100 / total)
            if block % 64 == 0 or done >= total:
                _log(cb, f"Downloading TES3MP… {pct}%")

        partial = zip_path.with_suffix(zip_path.suffix + ".part")
        partial.unlink(missing_ok=True)
        try:
            urlretrieve(TES3MP_DOWNLOAD_URL, partial, reporthook=_hook)
            if not _valid_tes3mp_zip(partial, TES3MP_ZIP_SHA256):
                raise RuntimeError("The TES3MP download failed its SHA-256 verification.")
            partial.replace(zip_path)
        finally:
            partial.unlink(missing_ok=True)

    _extract_zip(zip_path, dest, cb)
    ready = tes3mp_ready(dest)
    if not ready:
        raise RuntimeError("TES3MP download finished but tes3mp.exe is missing.")
    _log(cb, f"TES3MP {TES3MP_VERSION} ready.")
    return ready


def ensure_tes3mp(cb: ProgressCb | None = None) -> Path:
    ready = tes3mp_ready()
    if ready:
        return ready
    return download_tes3mp(cb)


def repair_tes3mp(cb: ProgressCb | None = None) -> Path:
    """Redownload and merge a verified engine archive while preserving server saves."""
    _log(cb, "Repairing TES3MP with a fresh verified download...")
    ready = download_tes3mp(cb, force=True)
    _log(cb, f"TES3MP {TES3MP_VERSION} repair complete.")
    return ready


@dataclass
class NetworkInterface:
    ip: str
    kind: str  # "lan" | "hamachi" | "tailscale" | "other"

    @property
    def stream_safe(self) -> bool:
        """Safe to auto-fill into an invite a streamer might have visible on screen.

        LAN IPs are excluded by default: while a bare 192.168.x.x address isn't
        directly dialable from the internet, showing it on stream still reveals
        subnet layout and — more importantly — is exactly the kind of detail a
        streamer reasonably doesn't want broadcast without an explicit choice to
        do so. Hamachi/Tailscale addresses are virtual-network identifiers
        created specifically to be shared with named peers, so they're treated
        as intentional-to-share by default.
        """
        return self.kind in ("hamachi", "tailscale")

    @property
    def label(self) -> str:
        return {"lan": "LAN", "hamachi": "Hamachi", "tailscale": "Tailscale", "other": "Network"}[
            self.kind
        ]


def _classify_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "other"
    # Hamachi assigns a fixed 25.0.0.0/8 block (LogMeIn-owned public range,
    # used privately as a virtual-network space) — verified against LogMeIn's
    # own docs, not guessed from convention.
    if addr in ipaddress.ip_network("25.0.0.0/8"):
        return "hamachi"
    # Tailscale's CGNAT range (100.64.0.0/10) — the address this machine's own
    # Tailscale adapter presents as (confirmed via gethostbyname_ex on this box).
    if addr in ipaddress.ip_network("100.64.0.0/10"):
        return "tailscale"
    if addr.is_private:
        return "lan"
    return "other"


def list_network_interfaces() -> list[NetworkInterface]:
    """All local IPv4 addresses this machine currently has, classified by network kind.

    Does NOT include the loopback address. Order is whatever gethostbyname_ex
    returns (not guaranteed stable), so callers should sort/prioritize explicitly
    rather than assume index 0 is meaningful.
    """
    try:
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        addrs = []
    seen: set[str] = set()
    interfaces: list[NetworkInterface] = []
    for ip in addrs:
        if ip in seen or ip.startswith("127."):
            continue
        seen.add(ip)
        interfaces.append(NetworkInterface(ip=ip, kind=_classify_ip(ip)))
    return interfaces


def local_ipv4() -> str:
    """Best-effort LAN IP — direct-route source address, used only for local/manual use
    (e.g. logging), never auto-filled into a shareable invite. See list_network_interfaces()
    for the stream-safety-aware selection used by the invite flow."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def prepare_profile(install: MorrowindInstall, pack: PackDef | None = None) -> Path:
    return ensure_mp_profile(install, pack or VANILLA)


def _resolve_pack(pack: PackDef | str | None) -> PackDef:
    if isinstance(pack, PackDef):
        return pack
    if isinstance(pack, str):
        return get_pack(pack)
    return VANILLA


def _client_launch_command(
    exe: Path, engine: Path, install: MorrowindInstall, pack: PackDef
) -> list[str]:
    """Use TES3MP's native profile path after MorrowFriends prepares it."""
    _ = engine, install, pack
    return [str(exe)]


def start_server(
    install: MorrowindInstall,
    hostname: str = "MorrowFriends",
    port: int = DEFAULT_PORT,
    password: str = "",
    pack: PackDef | str | None = None,
    cb: ProgressCb | None = None,
) -> tuple[subprocess.Popen, Invite]:
    pack = _resolve_pack(pack)
    ok, msg, missing = pack_status(install, pack)
    if not ok:
        raise RuntimeError(f"{msg} Missing: {', '.join(missing)}")

    engine = ensure_tes3mp(cb)
    prepare_profile(install, pack)
    write_server_cfg(hostname=hostname, port=port, password=password)
    write_client_cfg(host="localhost", port=port, password=password)
    sync_engine_configs(engine, install=install, pack=pack, is_server=True)
    apply_coop_rules(engine)
    _log(cb, coop_summary())
    _log(cb, f"Pack: {pack.label} — {msg}")

    exe = engine / "tes3mp-server.exe"
    _log(cb, f"Starting server on port {port}…")
    proc = subprocess.Popen(
        [str(exe)],
        cwd=str(engine),
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
    )
    # Host is intentionally left blank here — which network address (if any) is
    # safe to embed is a caller decision (e.g. a streamer not wanting their LAN
    # IP auto-filled onto a visible screen). See list_network_interfaces() and
    # NetworkInterface.stream_safe; the UI is responsible for filling invite.host.
    invite = Invite(
        host="",
        port=port,
        password=password,
        engine=TES3MP_VERSION,
        profile=pack.id,
    )
    return proc, invite


def start_client(
    install: MorrowindInstall,
    invite: Invite,
    pack: PackDef | str | None = None,
    cb: ProgressCb | None = None,
) -> subprocess.Popen:
    if invite.engine and invite.engine != TES3MP_VERSION:
        raise RuntimeError(
            f"Invite wants TES3MP {invite.engine}, this app is pinned to {TES3MP_VERSION}."
        )

    # Invite pack wins when present; UI pack is fallback for bare ip:port
    pack_id = invite.profile or (pack.id if isinstance(pack, PackDef) else pack) or "vanilla"
    pack = _resolve_pack(pack_id)
    ok, msg, missing = pack_status(install, pack)
    if not ok:
        raise RuntimeError(f"{msg} Missing: {', '.join(missing)}")

    engine = ensure_tes3mp(cb)
    prepare_profile(install, pack)
    ensure_native_openmw_profile(install, pack)
    write_client_cfg(host=invite.host, port=invite.port, password=invite.password)
    sync_engine_configs(engine, install=install, pack=pack)
    _log(cb, f"Pack: {pack.label} — {msg}")

    # Prove the engine will dial the party, not localhost. TES3MP reads the
    # destination only from this file and fails SILENTLY when it is wrong: the
    # game opens, connects to nobody, and looks like a network problem.
    mismatch = verify_client_destination(engine, invite.host, invite.port)
    if mismatch:
        raise RuntimeError(
            f"Could not point TES3MP at the party — {mismatch}. "
            "Close TES3MP if it is open, then press Play again."
        )

    exe = engine / "tes3mp.exe"
    _log(cb, f"Launching client → {invite.host}:{invite.port}")
    return subprocess.Popen(
        _client_launch_command(exe, engine, install, pack),
        cwd=str(engine),
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
    )


def start_client_local_host(
    install: MorrowindInstall,
    port: int = DEFAULT_PORT,
    password: str = "",
    pack: PackDef | str | None = None,
    cb: ProgressCb | None = None,
) -> subprocess.Popen:
    pack = _resolve_pack(pack)
    invite = Invite(
        host="127.0.0.1",
        port=port,
        password=password,
        profile=pack.id,
    )
    return start_client(install, invite, pack=pack, cb=cb)


def reset_character_password(player_name: str, new_password: str) -> bool:
    """Set a known password on a saved character, keeping their progress.

    NEVER just delete passwordHash/passwordSalt. HasAccount() is true whenever
    the record loads, so the server still shows the LOGIN dialog, and stock
    eventHandler.lua then does:

        local passwordSalt = Players[pid].data.login.passwordSalt   -- nil
        ... tes3mp.GetSHA256Hash(data .. passwordSalt)              -- concat nil

    Concatenating nil errors inside a C++ callback and takes the whole server
    down with ucrtbase 0xc0000409 — every time that player tries to log in.
    That is what happened on 2026-08-18: five server crashes, all traced to one
    credential-less record. Write a real salt+hash instead.

    Returns True when the record was updated.
    """
    import hashlib
    import json
    import secrets

    name = player_name.strip()
    if not name or not new_password:
        return False
    path = tes3mp_dir() / "server" / "data" / "player" / f"{name}.json"
    if not path.is_file():
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict):
        return False

    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    salt = "".join(secrets.choice(alphabet) for _ in range(64))
    login = record.get("login")
    if not isinstance(login, dict):
        login = {}
    login["name"] = login.get("name", name)
    login["passwordSalt"] = salt
    login["passwordHash"] = hashlib.sha256(
        (new_password + salt).encode("utf-8")
    ).hexdigest()
    record["login"] = login

    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(record, indent=2), encoding="utf-8")
    staging.replace(path)
    return True


def accounts_missing_credentials() -> list[str]:
    """Names whose saved record would crash the server on login (see above)."""
    import json

    folder = tes3mp_dir() / "server" / "data" / "player"
    if not folder.is_dir():
        return []
    broken: list[str] = []
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        login = record.get("login")
        login = login if isinstance(login, dict) else {}
        if not login.get("passwordHash") or not login.get("passwordSalt"):
            broken.append(path.stem)
    return broken
