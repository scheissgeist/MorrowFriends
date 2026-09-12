"""Runtime Tailscale capability discovery for guided private joining."""

from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TailscaleCapability:
    required: bool
    installed: bool
    running: bool
    peer_visible: bool
    peer_name: str = ""
    self_ip: str = ""
    error: str = ""

    @property
    def ready(self) -> bool:
        return not self.required or (
            self.installed and self.running and self.peer_visible
        )


def is_tailscale_ip(host: str) -> bool:
    try:
        return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def _tailscale_executable() -> str | None:
    found = shutil.which("tailscale") or shutil.which("tailscale.exe")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Tailscale"
        / "tailscale.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Tailscale" / "tailscale.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _peer_nodes(payload: dict) -> list[dict]:
    peers = payload.get("Peer", {})
    if isinstance(peers, dict):
        return [node for node in peers.values() if isinstance(node, dict)]
    if isinstance(peers, list):
        return [node for node in peers if isinstance(node, dict)]
    return []


def probe_tailscale(target_host: str = "") -> TailscaleCapability:
    required = is_tailscale_ip(target_host)
    executable = _tailscale_executable()
    if executable is None:
        return TailscaleCapability(required, False, False, not required)

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(
            [executable, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=creationflags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return TailscaleCapability(required, True, False, not required, error=str(exc))

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return TailscaleCapability(required, True, False, not required, error=detail)

    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        return TailscaleCapability(required, True, False, not required, error=str(exc))

    running = payload.get("BackendState") == "Running"
    self_node = payload.get("Self", {}) if isinstance(payload.get("Self"), dict) else {}
    # `.get(key, [])` returns None when the key is PRESENT with a null value,
    # which is what Tailscale emits for a node that has no assigned addresses
    # yet. `or []` covers both the missing key and the explicit null; without
    # it Play dies with "'NoneType' object is not iterable" on a machine that
    # just joined the tailnet (reported 2026-08-18).
    self_ips = self_node.get("TailscaleIPs") or []
    self_ip = next((str(ip) for ip in self_ips if str(ip).startswith("100.")), "")

    if not required:
        return TailscaleCapability(False, True, running, True, self_ip=self_ip)

    target = target_host.strip()
    for peer in _peer_nodes(payload):
        ips = [str(ip) for ip in (peer.get("TailscaleIPs") or [])]
        if target in ips:
            return TailscaleCapability(
                True,
                True,
                running,
                bool(peer.get("Online", True)),
                peer_name=str(peer.get("HostName", "")),
                self_ip=self_ip,
            )

    return TailscaleCapability(True, True, running, False, self_ip=self_ip)
