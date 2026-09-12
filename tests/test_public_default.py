"""Play must reach the public Skyhole server with no network setup.

Until 2026-08-18 the default host was a Tailscale address, so every friend
needed a Tailscale account plus an accepted device share before they could
play. That share flow stranded two people for an evening.
"""
from __future__ import annotations

import unittest

from app.invite import Invite
from app.play import (
    DEFAULT_PARTY_HOST,
    resolve_friend_invite,
)
from app.tailscale import is_tailscale_ip


class PublicDefaultTests(unittest.TestCase):
    def test_default_host_is_not_a_tailscale_address(self):
        self.assertFalse(is_tailscale_ip(DEFAULT_PARTY_HOST))

    def test_play_resolves_to_the_public_server(self):
        invite = resolve_friend_invite(saved_token="", share_url="")
        self.assertEqual(invite.host, DEFAULT_PARTY_HOST)
        self.assertEqual(invite.port, 25565)

    def test_invite_has_no_server_password(self):
        """The public server is open. A leftover password would be sent in
        tes3mp.cfg and is unnecessary; TES3MP still lets old zips through."""
        invite = resolve_friend_invite(saved_token="", share_url="")
        self.assertEqual(invite.password, "")

    def test_a_stale_tailscale_token_is_ignored(self):
        stale = Invite(host="100.110.37.122", port=25565).to_token()
        invite = resolve_friend_invite(saved_token=stale, share_url="")
        self.assertEqual(invite.host, DEFAULT_PARTY_HOST)

    def test_a_public_token_is_still_honoured(self):
        token = Invite(host="203.0.113.9", port=25565).to_token()
        self.assertEqual(resolve_friend_invite(saved_token=token, share_url="").host,
                         "203.0.113.9")

    def test_no_share_url_is_needed(self):
        """A public host must not demand a Tailscale share."""
        invite = resolve_friend_invite(saved_token="", share_url="")
        self.assertEqual(invite.host, DEFAULT_PARTY_HOST)


if __name__ == "__main__":
    unittest.main()
