"""Invite strings for Host → Join."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .paths import DEFAULT_PORT, TES3MP_VERSION


@dataclass
class Invite:
    host: str
    port: int = DEFAULT_PORT
    password: str = ""
    engine: str = TES3MP_VERSION
    profile: str = "vanilla"
    share_url: str = ""

    def to_string(self) -> str:
        """Human-friendly primary form + compact token."""
        base = f"{self.host}:{self.port}"
        if self.password:
            return f"{base}|pw={self.password}|eng={self.engine}|pack={self.profile}"
        return f"{base}|eng={self.engine}|pack={self.profile}"

    def to_token(self) -> str:
        payload = {
            "h": self.host,
            "p": self.port,
            "pw": self.password,
            "e": self.engine,
            "k": self.profile,
        }
        prefix = "mf1."
        if self.share_url:
            payload["s"] = validate_tailscale_share_url(self.share_url)
            prefix = "mf2."
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return prefix + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def is_tailscale_share_url(text: str) -> bool:
    try:
        parsed = urlparse(text.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    if parsed.hostname not in {"login.tailscale.com", "console.tailscale.com"}:
        return False
    path = parsed.path.rstrip("/")
    token = path.split("/")[-1]
    if len(token) < 8:
        return False
    # Two different Tailscale links look similar and behave completely
    # differently. `/f/<token>` is a DEVICE share: it exposes this one machine
    # to the friend, which is what probe_tailscale() looks for in their peer
    # list. `/admin/invite/<token>` is a TAILNET invite: it pulls the friend's
    # devices into our network but never makes the host visible to them, so
    # Play loops forever on "accept the share". Accept both here so an already
    # distributed link keeps working; is_device_share_url() tells them apart.
    return path.startswith("/f/") or path.startswith("/admin/invite/")


def is_device_share_url(text: str) -> bool:
    """True only for `/f/<token>` device shares, the link Play actually needs."""
    try:
        parsed = urlparse(text.strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in {"login.tailscale.com", "console.tailscale.com"}
        and parsed.path.rstrip("/").startswith("/f/")
        and len(parsed.path.rstrip("/").split("/")[-1]) >= 8
    )


def validate_tailscale_share_url(text: str) -> str:
    value = text.strip()
    if not is_tailscale_share_url(value):
        raise ValueError("Paste a valid Tailscale machine-share link.")
    return value


def parse_invite(text: str) -> Invite:
    text = text.strip()
    if not text:
        raise ValueError("Invite is empty.")

    if is_tailscale_share_url(text):
        raise ValueError(
            "That is the Tailscale access link, not the MorrowFriends game invite. "
            "Open it in your browser, then paste the private party invite here."
        )

    if text.startswith(("mf1.", "mf2.")):
        b64 = text[4:]
        pad = "=" * (-len(b64) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(b64 + pad))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("Invalid invite token.") from exc
        invite = Invite(
            host=str(data.get("h", "")),
            port=int(data.get("p", DEFAULT_PORT)),
            password=str(data.get("pw", "")),
            engine=str(data.get("e", TES3MP_VERSION)),
            profile=str(data.get("k", "vanilla")),
            share_url=str(data.get("s", "")),
        )
        if not invite.host:
            raise ValueError("Invite is missing a host address.")
        if invite.share_url:
            validate_tailscale_share_url(invite.share_url)
        return invite

    # host:port or host:port|pw=...|eng=...
    host_port, *rest = text.split("|")
    host_port = host_port.strip()
    m = re.match(r"^(\[?[A-Za-z0-9.\-:]+\]?):(\d+)$", host_port)
    if m:
        host, port_s = m.group(1), m.group(2)
        # strip IPv6 brackets if present
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        port = int(port_s)
    else:
        # bare IP / hostname → default port
        if ":" in host_port and not host_port.count(":") == 1:
            # likely IPv6 without port
            host = host_port.strip("[]")
            port = DEFAULT_PORT
        elif re.match(r"^[^:]+:\d+$", host_port):
            host, port_s = host_port.rsplit(":", 1)
            port = int(port_s)
        else:
            host = host_port
            port = DEFAULT_PORT

    password = ""
    engine = TES3MP_VERSION
    profile = "vanilla"
    for part in rest:
        part = part.strip()
        if part.startswith("pw="):
            password = part[3:]
        elif part.startswith("eng="):
            engine = part[4:]
        elif part.startswith("pack="):
            profile = part[5:]

    if not host:
        raise ValueError("Invite is missing a host address.")
    return Invite(host=host, port=port, password=password, engine=engine, profile=profile)
