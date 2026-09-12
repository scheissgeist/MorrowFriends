import unittest

from app.chat_inject import tes3mp_window_titles


class ChatInjectTests(unittest.TestCase):
    def test_tes3mp_titles_are_recognized(self) -> None:
        matches = tes3mp_window_titles(
            ["TES3MP 0.8.1", "Notepad", "Morrowind: Tribunal"]
        )
        self.assertEqual(matches, ["TES3MP 0.8.1", "Morrowind: Tribunal"])

    def test_unrelated_windows_are_ignored(self) -> None:
        self.assertEqual(tes3mp_window_titles(["Chrome", "Discord"]), [])


if __name__ == "__main__":
    unittest.main()
