"""Play must never refuse to launch on a precondition.

On 2026-08-18 two friends (rettycombine, sluxslol) were stuck in an infinite
"accept the tailscale share" loop while other players connected to the same
server without trouble. The gate was stricter than the thing it guarded.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.invite import Invite
from app.play import diagnose_failed_join, preflight_friend_invite
from app.tailscale import TailscaleCapability

TAILNET_INVITE = "https://login.tailscale.com/admin/invite/x7TcYJ9RGcWbv2UCjNfJ11"
DEVICE_SHARE = "https://login.tailscale.com/f/x7TcYJ9RGcWbv2UCjNfJ11"


def _cap(**kw):
    base = dict(required=True, installed=True, running=True, peer_visible=True)
    base.update(kw)
    return TailscaleCapability(**base)


class PreflightNeverBlocksTests(unittest.TestCase):
    def test_preflight_never_raises_even_when_nothing_is_visible(self):
        invite = Invite(host="100.110.37.122", port=25565, share_url=TAILNET_INVITE)
        with patch(
            "app.play.probe_tailscale",
            return_value=_cap(installed=False, running=False, peer_visible=False),
        ):
            self.assertIsNone(preflight_friend_invite(invite))

    def test_preflight_never_raises_for_a_public_host(self):
        self.assertIsNone(preflight_friend_invite(Invite(host="203.0.113.7", port=25565)))


class DiagnoseAfterFailureTests(unittest.TestCase):
    def test_tailnet_invite_is_named_as_the_cause(self):
        invite = Invite(host="100.110.37.122", port=25565, share_url=TAILNET_INVITE)
        with patch("app.play.probe_tailscale", return_value=_cap(peer_visible=False)):
            self.assertIn("tailnet invite", diagnose_failed_join(invite))

    def test_device_share_gets_the_generic_not_visible_message(self):
        invite = Invite(host="100.110.37.122", port=25565, share_url=DEVICE_SHARE)
        with patch("app.play.probe_tailscale", return_value=_cap(peer_visible=False)):
            msg = diagnose_failed_join(invite)
            self.assertIn("not visible", msg)
            self.assertNotIn("tailnet invite", msg)

    def test_public_host_failure_never_mentions_tailscale(self):
        msg = diagnose_failed_join(Invite(host="203.0.113.7", port=25565))
        self.assertNotIn("Tailscale", msg)
        self.assertIn("Could not reach", msg)

    def test_healthy_tailscale_yields_no_conclusion(self):
        invite = Invite(host="100.110.37.122", port=25565, share_url=DEVICE_SHARE)
        with patch("app.play.probe_tailscale", return_value=_cap()):
            self.assertEqual(diagnose_failed_join(invite), "")


if __name__ == "__main__":
    unittest.main()
