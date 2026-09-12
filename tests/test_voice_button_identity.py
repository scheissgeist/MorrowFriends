"""The Open voice button must identify the player itself.

Morrowind runs fullscreen and its chat is not selectable text, so a code shown
in game frequently CANNOT be copied out at all. The server
already writes a code -> player map, so the launcher never needs to ask.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.voice_auto import pending_claim_code, voice_join_url


class ClaimLookupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        data = self.root / "server" / "data"
        data.mkdir(parents=True)
        (data / "voice_claims.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "serverUptimeMs": 1000,
                    "claims": {
                        "Z7JEWS0W1Z9NXJPM": {"player": "Gorid"},
                        "RBGGANNNOFKHGDXQ": {"player": "Sluxslol"},
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_code_is_found_by_player_name(self):
        self.assertEqual(pending_claim_code("Gorid", self.root), "Z7JEWS0W1Z9NXJPM")

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(pending_claim_code("gorid", self.root), "Z7JEWS0W1Z9NXJPM")

    def test_unknown_player_returns_none_not_a_wrong_code(self):
        self.assertIsNone(pending_claim_code("Nobody", self.root))

    def test_empty_name_returns_none(self):
        self.assertIsNone(pending_claim_code("", self.root))


class JoinUrlTests(unittest.TestCase):
    def test_url_carries_the_code_when_known(self):
        url = voice_join_url(
            player="Gorid",
            code="Z7JEWS0W1Z9NXJPM",
            ptt={"kind": "keyboard", "code": "Space", "label": "Space"},
        )
        self.assertIn("player=Gorid", url)
        self.assertIn("code=Z7JEWS0W1Z9NXJPM", url)

    def test_url_falls_back_to_auto_when_no_code(self):
        url = voice_join_url(
            player="Gorid",
            code="",
            ptt={"kind": "keyboard", "code": "Space", "label": "Space"},
        )
        self.assertIn("auto=1", url)
        self.assertNotIn("code=", url)


if __name__ == "__main__":
    unittest.main()
