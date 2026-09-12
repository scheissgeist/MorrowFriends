"""In-game push-to-talk indicator state file.

TES3MP 0.8.1 exposes no persistent HUD to server Lua (verified against
docs.tes3mp.com GUI Functions: only MessageBox / CustomMessageBox / InputDialog
/ PasswordDialog / ListBox / quick keys / SetMapVisibility, all modal). The one
zero-recompile channel onto the game screen is a chat line, which fades after
`delay` seconds when the client chat is in CHAT_HIDDENMODE
(GUIChat::update in the shipped Source.zip).

The launcher publishes its mic state here; the roster Lua reads it on the same
200ms tick it writes positions, so the indicator does not lag behind the key.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import write_ptt_state


class WritePttStateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / "server" / "data" / "ptt_state.json"

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def test_talking_state_is_written(self):
        write_ptt_state(self.root, "Gorid", True)
        payload = self._read()
        self.assertEqual(payload["player"], "Gorid")
        self.assertIs(payload["talking"], True)

    def test_released_state_is_written(self):
        write_ptt_state(self.root, "Gorid", False)
        self.assertIs(self._read()["talking"], False)

    def test_payload_is_versioned(self):
        # The Lua reader rejects anything whose version is not 1, the same way
        # the relay bridge rejects an unversioned position snapshot.
        write_ptt_state(self.root, "Gorid", True)
        self.assertEqual(self._read()["version"], 1)

    def test_name_is_trimmed(self):
        write_ptt_state(self.root, "  Gorid  ", True)
        self.assertEqual(self._read()["player"], "Gorid")

    def test_directory_is_created_when_absent(self):
        fresh = Path(tempfile.mkdtemp()) / "nested"
        write_ptt_state(fresh, "Gorid", True)
        self.assertTrue((fresh / "server" / "data" / "ptt_state.json").is_file())

    def test_repeated_writes_replace_not_append(self):
        write_ptt_state(self.root, "Gorid", True)
        write_ptt_state(self.root, "Gorid", False)
        self.assertIs(self._read()["talking"], False)


class ChatDelayTests(unittest.TestCase):
    def test_client_cfg_uses_a_short_fade(self):
        """delay feeds GUIChat::setDelay(); 5s left the indicator stuck on screen."""
        from app import config

        import inspect

        source = inspect.getsource(config.write_client_cfg)
        self.assertIn("delay = 2.0", source)


if __name__ == "__main__":
    unittest.main()
