from __future__ import annotations

import unittest

from app.invite import (
    Invite,
    is_device_share_url,
    is_tailscale_share_url,
    parse_invite,
)


SHARE_URL = "https://login.tailscale.com/admin/invite/exampleInvite123"


class InviteTests(unittest.TestCase):
    def test_party_token_round_trip(self) -> None:
        original = Invite(
            host="100.110.37.122",
            password="secret",
            profile="vanilla",
            share_url=SHARE_URL,
        )
        token = original.to_token()
        self.assertTrue(token.startswith("mf2."))
        parsed = parse_invite(token)
        self.assertEqual(parsed.host, original.host)
        self.assertEqual(parsed.password, "secret")
        self.assertEqual(parsed.share_url, SHARE_URL)

    def test_legacy_token_stays_compatible(self) -> None:
        token = Invite(host="192.168.1.5").to_token()
        self.assertTrue(token.startswith("mf1."))
        self.assertEqual(parse_invite(token).host, "192.168.1.5")

    def test_share_link_has_friendly_wrong_box_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tailscale access link"):
            parse_invite(SHARE_URL)

    def test_rejects_untrusted_share_url(self) -> None:
        self.assertFalse(is_tailscale_share_url("https://example.com/admin/invite/nope"))
        with self.assertRaisesRegex(ValueError, "valid Tailscale"):
            Invite(
                host="100.110.37.122",
                share_url="https://example.com/admin/invite/nope",
            ).to_token()


if __name__ == "__main__":
    unittest.main()


class TailscaleShareKindTests(unittest.TestCase):
    """`/f/` device shares expose the host; `/admin/invite/` tailnet invites do not.

    Shipping the wrong one made Play loop forever on "accept the share" for a
    friend on 2026-08-18: they accepted, the host still was not a visible peer,
    and Play repeated the same instruction.
    """

    DEVICE = "https://login.tailscale.com/f/x7TcYJ9RGcWbv2UCjNfJ11"
    TAILNET = "https://login.tailscale.com/admin/invite/x7TcYJ9RGcWbv2UCjNfJ11"

    def test_device_share_is_recognised(self):
        self.assertTrue(is_device_share_url(self.DEVICE))

    def test_tailnet_invite_is_not_a_device_share(self):
        self.assertFalse(is_device_share_url(self.TAILNET))

    def test_both_forms_still_validate_as_share_urls(self):
        self.assertTrue(is_tailscale_share_url(self.DEVICE))
        self.assertTrue(is_tailscale_share_url(self.TAILNET))

    def test_junk_is_rejected_by_both(self):
        for bad in ("", "http://login.tailscale.com/f/abcdefgh", "https://evil.com/f/abcdefgh"):
            self.assertFalse(is_device_share_url(bad), bad)
            self.assertFalse(is_tailscale_share_url(bad), bad)
