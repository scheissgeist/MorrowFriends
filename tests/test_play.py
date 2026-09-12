import unittest
from unittest.mock import patch

from app.invite import Invite
from app.play import DEFAULT_PARTY_HOST, PlayError, resolve_friend_invite
from app.tailscale import TailscaleCapability


SHARE_URL = "https://login.tailscale.com/admin/invite/exampleInvite123"


class PlayResolveTests(unittest.TestCase):
    def test_startup_invite_wins(self) -> None:
        startup = Invite(host="100.64.1.2", share_url=SHARE_URL)
        resolved = resolve_friend_invite(startup=startup, saved_token="")
        self.assertEqual(resolved.host, "100.64.1.2")

    def test_saved_public_token_is_used_when_present(self) -> None:
        token = Invite(host="203.0.113.9", share_url=SHARE_URL).to_token()
        resolved = resolve_friend_invite(startup=None, saved_token=token)
        self.assertEqual(resolved.host, "203.0.113.9")

    def test_saved_tailscale_token_is_ignored_for_the_public_server(self) -> None:
        # A friend who played on the old Tailscale party still has that token
        # saved. Honouring it would send them to a host they can no longer
        # reach while Play looked like it was working.
        token = Invite(host="100.64.9.9", share_url=SHARE_URL).to_token()
        resolved = resolve_friend_invite(startup=None, saved_token=token)
        self.assertEqual(resolved.host, DEFAULT_PARTY_HOST)

    def test_visible_tailscale_host_builds_an_invite(self) -> None:
        # Tailscale parties still work when one is explicitly requested.
        capability = TailscaleCapability(True, True, True, True, peer_name="heller")
        with patch("app.play.probe_tailscale", return_value=capability):
            resolved = resolve_friend_invite(
                startup=None,
                saved_token="",
                share_url=SHARE_URL,
                default_host="100.110.37.122",
            )
        self.assertEqual(resolved.host, "100.110.37.122")
        self.assertEqual(resolved.share_url, SHARE_URL)

    def test_public_default_needs_no_tailscale(self) -> None:
        resolved = resolve_friend_invite(startup=None, saved_token="", share_url="")
        self.assertEqual(resolved.host, DEFAULT_PARTY_HOST)

    def test_missing_tailscale_party_asks_for_a_link_once(self) -> None:
        # Only reachable when a TAILSCALE host is explicitly requested. With the
        # public default there is always a party to join, so Play no longer has
        # a "no party" dead end at all.
        capability = TailscaleCapability(True, False, False, False)
        with patch("app.play.probe_tailscale", return_value=capability):
            with self.assertRaises(PlayError) as raised:
                resolve_friend_invite(
                    startup=None,
                    saved_token="",
                    share_url="",
                    default_host="100.110.37.122",
                )
        self.assertEqual(raised.exception.action, "invite")

    def test_public_default_never_dead_ends(self) -> None:
        """No Tailscale, no share, no saved link — Play still has a server."""
        resolved = resolve_friend_invite(startup=None, saved_token="", share_url="")
        self.assertEqual(resolved.host, DEFAULT_PARTY_HOST)
        self.assertEqual(resolved.password, "")


if __name__ == "__main__":
    unittest.main()
