import unittest

from app.ptt_binding import (
    binding_from_tk_key,
    binding_from_tk_mouse,
    normalize_ptt_binding,
    ptt_wire_value,
)


class PttBindingTests(unittest.TestCase):
    def test_space_and_letter_keys(self) -> None:
        self.assertEqual(
            binding_from_tk_key("space"),
            {"kind": "keyboard", "code": "Space", "label": "Space"},
        )
        self.assertEqual(
            binding_from_tk_key("v"),
            {"kind": "keyboard", "code": "KeyV", "label": "V"},
        )
        self.assertEqual(
            binding_from_tk_key("F12"),
            {"kind": "keyboard", "code": "F12", "label": "F12"},
        )

    def test_escape_cancels(self) -> None:
        self.assertIsNone(binding_from_tk_key("Escape"))

    def test_tk_mouse_matches_the_browser_button_index(self) -> None:
        self.assertEqual(binding_from_tk_mouse(1)["button"], 0)
        self.assertEqual(binding_from_tk_mouse(3)["button"], 2)
        self.assertIsNone(binding_from_tk_mouse(4))

    def test_rejects_a_broken_saved_binding(self) -> None:
        self.assertIsNone(normalize_ptt_binding({"kind": "keyboard", "code": "??", "label": "x"}))
        self.assertIsNone(normalize_ptt_binding({"kind": "mouse", "button": 9, "label": "x"}))

    def test_wire_value_matches_the_page_query(self) -> None:
        self.assertEqual(
            ptt_wire_value({"kind": "keyboard", "code": "KeyV", "label": "V"}),
            "KeyV",
        )
        self.assertEqual(
            ptt_wire_value({"kind": "mouse", "button": 3, "label": "Mouse Back"}),
            "3",
        )


if __name__ == "__main__":
    unittest.main()
