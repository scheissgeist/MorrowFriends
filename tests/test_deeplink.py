import unittest

from app.deeplink import invite_to_deeplink, parse_deeplink
from app.invite import Invite


SHARE_URL = "https://login.tailscale.com/admin/invite/exampleInvite123"


class DeeplinkTests(unittest.TestCase):
    def test_round_trip_join_link(self) -> None:
        invite = Invite(
            host="100.110.37.122",
            password="secret",
            share_url=SHARE_URL,
        )
        link = invite_to_deeplink(invite)
        self.assertTrue(link.startswith("morrowfriends://join/mf2."))
        parsed = parse_deeplink(link)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.host, invite.host)
        self.assertEqual(parsed.password, "secret")
        self.assertEqual(parsed.share_url, SHARE_URL)

    def test_query_form_is_accepted(self) -> None:
        invite = Invite(host="100.110.37.122", share_url=SHARE_URL)
        token = invite.to_token()
        parsed = parse_deeplink(f"morrowfriends://join?invite={token}")
        self.assertEqual(parsed.host, "100.110.37.122")


if __name__ == "__main__":
    unittest.main()
