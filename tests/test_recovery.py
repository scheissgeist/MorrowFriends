import unittest

from app.play import PlayError
from app.recovery import RECOVERY_ACTION_LABELS, normalize_voice_code


class VoiceCodeTests(unittest.TestCase):
    def test_empty_code_opens_voice_without_a_claim(self) -> None:
        self.assertEqual(normalize_voice_code("  "), "")

    def test_sixteen_character_code_is_normalized(self) -> None:
        self.assertEqual(normalize_voice_code("ab12 cd34 ef56 gh78"), "AB12CD34EF56GH78")

    def test_short_code_is_rejected(self) -> None:
        with self.assertRaises(PlayError) as raised:
            normalize_voice_code("ABCD")
        self.assertEqual(raised.exception.action, "voice")


class RecoveryActionTests(unittest.TestCase):
    """The drawer tests went with the drawer (2026-08-20).

    drawer_label/show_recovery_tools decided when the inline "Something's wrong"
    panel appeared. That panel is gone — settings live behind the gear and the
    escape hatch is the "Fix this" button — so the functions and their tests
    were removed rather than left guarding UI that no longer exists.
    """

    def test_every_action_a_friend_can_get_has_a_label(self) -> None:
        # These are the actions _run_play_recovery dispatches on.
        for action in ("browse", "vc", "invite", "voice", "repair"):
            self.assertIn(action, RECOVERY_ACTION_LABELS)
            self.assertTrue(RECOVERY_ACTION_LABELS[action].strip())

    def test_tailscale_actions_are_gone(self) -> None:
        self.assertNotIn("tailscale", RECOVERY_ACTION_LABELS)
        self.assertNotIn("share", RECOVERY_ACTION_LABELS)

    def test_invite_no_longer_asks_for_a_paste(self) -> None:
        # The paste field was removed; telling a friend to paste a link they
        # were never given is the failure this label used to cause.
        self.assertNotIn("paste", RECOVERY_ACTION_LABELS["invite"].lower())


if __name__ == "__main__":
    unittest.main()
