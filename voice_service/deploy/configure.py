"""Render a secret-safe single-node Hetzner deployment for MorrowFriends voice."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import socket
from pathlib import Path

DOMAIN_PATTERN = re.compile(
    r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
PARTY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def valid_domain(value: str) -> str:
    domain = value.strip().lower().rstrip(".")
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise argparse.ArgumentTypeError(f"invalid DNS name: {value}")
    return domain


def valid_party(value: str) -> str:
    party = value.strip()
    if not PARTY_PATTERN.fullmatch(party):
        raise argparse.ArgumentTypeError(
            "party ID must use 1-64 letters, numbers, underscores, or dashes"
        )
    return party


def local_route_ip() -> str:
    """Discover the non-loopback address Caddy should use for local TURN proxying."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("1.1.1.1", 53))
        address = probe.getsockname()[0]
    finally:
        probe.close()
    parsed = ipaddress.ip_address(address)
    if parsed.is_loopback or parsed.is_unspecified:
        raise RuntimeError("could not discover a non-loopback TURN upstream address")
    return address


def valid_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if address.version != 4 or address.is_loopback or address.is_unspecified:
        raise argparse.ArgumentTypeError("TURN upstream must be a non-loopback IPv4 address")
    return str(address)


def caddy_config(
    *, voice_domain: str, livekit_domain: str, turn_domain: str, turn_ip: str
) -> str:
    return f"""logging:
  logs:
    default:
      level: INFO
storage:
  module: file_system
  root: /data
apps:
  tls:
    certificates:
      automate:
        - {voice_domain}
        - {livekit_domain}
        - {turn_domain}
  layer4:
    servers:
      main:
        listen: [\":443\"]
        routes:
          - match:
              - tls:
                  sni: [\"{turn_domain}\"]
            handle:
              - handler: tls
              - handler: proxy
                upstreams:
                  - dial: [\"{turn_ip}:5349\"]
          - match:
              - tls:
                  sni: [\"{voice_domain}\"]
            handle:
              - handler: tls
                connection_policies:
                  - alpn: [\"http/1.1\"]
              - handler: proxy
                upstreams:
                  - dial: [\"127.0.0.1:8080\"]
          - match:
              - tls:
                  sni: [\"{livekit_domain}\"]
            handle:
              - handler: tls
                connection_policies:
                  - alpn: [\"http/1.1\"]
              - handler: proxy
                upstreams:
                  - dial: [\"127.0.0.1:7880\"]
"""


def livekit_config(*, turn_domain: str, shared_edge: bool = False) -> str:
    if shared_edge:
        return f"""port: 7880
bind_addresses:
  - 0.0.0.0
logging:
  level: info
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: true
turn:
  enabled: true
  domain: {turn_domain}
  udp_port: 3478
  relay_range_start: 35000
  relay_range_end: 35020
"""
    return f"""port: 7880
bind_addresses:
  - 0.0.0.0
logging:
  level: info
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: true
redis:
  address: 127.0.0.1:6379
turn:
  enabled: true
  domain: {turn_domain}
  tls_port: 5349
  udp_port: 3478
external_tls: true
"""


def shared_caddy_config(*, voice_domain: str, livekit_domain: str) -> str:
    return f"""# MorrowFriends voice -- restored automatically by
# /opt/morrowfriends/voice_service/deploy/ensure-edge-route.sh
{voice_domain} {{
    encode zstd gzip
    reverse_proxy morrowfriends-voice-relay:8080
    header {{
        -Server
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }}
}}

{livekit_domain} {{
    # LiveKit uses host networking so ICE sees the public media sockets.
    # This is the verified gateway of the shared hetzner_default network.
    reverse_proxy 172.19.0.1:7880
    header {{
        -Server
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
    }}
}}
"""


def environment_config(
    *, party_id: str, livekit_domain: str, api_key: str, api_secret: str, host_token: str
) -> str:
    return "\n".join(
        [
            f"MORROWVOICE_PARTY_ID={party_id}",
            f"MORROWVOICE_HOST_TOKEN={host_token}",
            f"LIVEKIT_URL=wss://{livekit_domain}",
            f"LIVEKIT_API_KEY={api_key}",
            f"LIVEKIT_API_SECRET={api_secret}",
            "",
        ]
    )


def _write_new(path: Path, content: str, *, mode: int, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; use --force to rotate it")
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(content, encoding="utf-8", newline="\n")
    os.chmod(staging, mode)
    staging.replace(path)


def configure(args: argparse.Namespace) -> dict[str, str]:
    domains = {args.voice_domain, args.livekit_domain, args.turn_domain}
    if len(domains) != 3:
        raise ValueError("voice, LiveKit, and TURN domains must be different")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    shared_edge = bool(getattr(args, "shared_edge", False))
    turn_ip = None if shared_edge else (args.turn_upstream_ip or local_route_ip())
    api_key = "MF" + secrets.token_hex(8)
    api_secret = secrets.token_urlsafe(36)
    host_token = secrets.token_urlsafe(36)

    if shared_edge:
        _write_new(
            output / "caddy.morrowfriends",
            shared_caddy_config(
                voice_domain=args.voice_domain,
                livekit_domain=args.livekit_domain,
            ),
            mode=0o644,
            force=args.force,
        )
    else:
        _write_new(
            output / "caddy.yaml",
            caddy_config(
                voice_domain=args.voice_domain,
                livekit_domain=args.livekit_domain,
                turn_domain=args.turn_domain,
                turn_ip=turn_ip,
            ),
            mode=0o644,
            force=args.force,
        )
    _write_new(
        output / "livekit.yaml",
        livekit_config(turn_domain=args.turn_domain, shared_edge=shared_edge),
        mode=0o644,
        force=args.force,
    )
    _write_new(
        output / ".env",
        environment_config(
            party_id=args.party_id,
            livekit_domain=args.livekit_domain,
            api_key=api_key,
            api_secret=api_secret,
            host_token=host_token,
        ),
        mode=0o600,
        force=args.force,
    )
    return {
        "friend_url": f"https://{args.voice_domain}/?party={args.party_id}",
        "relay_url": f"wss://{args.voice_domain}",
        "party_id": args.party_id,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Create MorrowFriends voice TLS, LiveKit, and secret configuration."
    )
    result.add_argument("--voice-domain", required=True, type=valid_domain)
    result.add_argument("--livekit-domain", required=True, type=valid_domain)
    result.add_argument("--turn-domain", required=True, type=valid_domain)
    result.add_argument("--party-id", required=True, type=valid_party)
    result.add_argument("--turn-upstream-ip", type=valid_ip)
    result.add_argument(
        "--shared-edge",
        action="store_true",
        help="render for an existing Caddy edge and Docker bridge network",
    )
    result.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    result.add_argument(
        "--force",
        action="store_true",
        help="rotate and replace existing deployment secrets and generated files",
    )
    return result


def main() -> None:
    args = parser().parse_args()
    rendered = configure(args)
    print("Voice deployment configuration created.")
    print(f"Relay URL: {rendered['relay_url']}")
    print(f"Party ID: {rendered['party_id']}")
    print(f"Friend URL: {rendered['friend_url']}")
    print("The host token is stored only in the mode-600 .env file.")


if __name__ == "__main__":
    main()
