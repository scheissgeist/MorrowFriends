"""One Play path: detect, prepare, join or host, then attach voice."""

from __future__ import annotations

from dataclasses import dataclass

from .deeplink import parse_deeplink
from .invite import Invite
from .preferences import load_friend_share_url, load_last_invite_token
from .tailscale import is_tailscale_ip, probe_tailscale

# Public Skyhole server. Was 100.110.37.122 — a Tailscale address, which meant
# every friend needed a Tailscale account and an accepted device share before
# they could play, and that share flow is what stranded two people on
# 2026-08-18. This host is reachable from the open internet (verified with a
# RakNet unconnected-ping returning ID_UNCONNECTED_PONG), so Play needs no
# network setup at all.
DEFAULT_PARTY_HOST = "5.78.187.172"
DEFAULT_PARTY_PORT = 25565
# Open server: TES3MP treats an empty password as unpassworded. Clients that
# still send the old baked-in password are accepted (TES3MP only kicks on a
# mismatch when the server itself has a password).
DEFAULT_PARTY_PASSWORD = ""


class PlayError(RuntimeError):
    def __init__(self, message: str, action: str = "") -> None:
        super().__init__(message)
        self.action = action


@dataclass(frozen=True)
class PlayProgress:
    step: str
    detail: str


def resolve_friend_invite(
    *,
    startup: Invite | None = None,
    saved_token: str | None = None,
    share_url: str | None = None,
    default_host: str = DEFAULT_PARTY_HOST,
) -> Invite:
    """Pick tonight's party without asking the friend to paste anything."""
    if startup is not None:
        return startup
    token = load_last_invite_token() if saved_token is None else saved_token
    if token:
        try:
            parsed = parse_deeplink(token)
        except ValueError:
            parsed = None
        # parse_deeplink returns None for an empty/blank token rather than
        # raising, so returning it directly could hand back None from a
        # function annotated -> Invite and crash the caller instead of falling
        # through to the share/default path below.
        # A saved token from a PREVIOUS party would silently override the
        # current default. Friends who played on the Tailscale server have one
        # stored, and honouring it would send them to a host they can no longer
        # reach while Play looked like it was working. Only trust a saved token
        # that still points somewhere reachable without extra setup.
        if parsed is not None and not is_tailscale_ip(parsed.host):
            return parsed
    share = load_friend_share_url() if share_url is None else share_url

    # A PUBLIC host needs no Tailscale, no share, and no pasted link — just
    # connect. Probing Tailscale here would gate a reachable server behind a
    # network the player does not need, which is exactly the loop that stranded
    # rettycombine and sluxslol on 2026-08-18.
    if not is_tailscale_ip(default_host):
        return Invite(
            host=default_host,
            port=DEFAULT_PARTY_PORT,
            password=DEFAULT_PARTY_PASSWORD,
            share_url=share,
        )

    capability = probe_tailscale(default_host)
    if capability.peer_visible or (
        capability.installed and capability.running and is_tailscale_ip(default_host)
    ):
        return Invite(host=default_host, port=DEFAULT_PARTY_PORT, share_url=share)
    if share:
        return Invite(host=default_host, port=DEFAULT_PARTY_PORT, share_url=share)
    raise PlayError(
        "Ask the host for a MorrowFriends link once. After that, Play is enough.",
        action="invite",
    )


def preflight_friend_invite(invite: Invite) -> None:
    """Deliberately does nothing. Kept so existing callers keep working.

    This used to refuse to launch unless the host showed up as a Tailscale
    peer. That check was STRICTER THAN THE THING IT GUARDED: on 2026-08-18 two
    friends (rettycombine, sluxslol) were stuck in an infinite "accept the
    share" loop while other players were connecting to the same server without
    trouble by pointing TES3MP at the address directly. A precondition that
    blocks people who would otherwise succeed is worse than no precondition.

    The connection attempt is now the test — see diagnose_failed_join(), which
    runs only AFTER a real failure and explains what actually went wrong.
    """
    return


def diagnose_failed_join(invite: Invite) -> str:
    """Explain a join that already failed. Never called before an attempt.

    Returns a single sentence for the UI, or "" when nothing conclusive was
    found — an empty string means "we do not know", which is a valid answer and
    better than inventing a cause.
    """
    if not is_tailscale_ip(invite.host):
        # Public host: the address is reachable or it is not. Nothing about
        # Tailscale is relevant, so do not mention it.
        return (
            "Could not reach the server. It may be offline, or the host's "
            "port may not be open yet."
        )

    capability = probe_tailscale(invite.host)
    if not capability.installed:
        return "This party needs Tailscale. Install it, sign in, then press Play."
    if not capability.running:
        return "Tailscale is installed but not connected. Open it, then press Play."
    if not capability.peer_visible:
        from .invite import is_device_share_url

        if invite.share_url and not is_device_share_url(invite.share_url):
            return (
                "That party link cannot let you in — it is a tailnet invite, "
                "not a machine share. Ask the host for a new link."
            )
        return (
            "The host is not visible on your Tailscale yet. Ask them to share "
            "the machine with you."
        )
    return ""
