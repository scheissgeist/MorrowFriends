import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.preferences import (
    load_character_password,
    load_host_player_name,
    load_known_player_names,
    load_ptt_binding,
    load_voice_enabled,
    save_character_password,
    save_host_player_name,
    save_last_player_name,
    save_ptt_binding,
    save_voice_enabled,
)


class HostIdentityPreferencesTests(unittest.TestCase):
    def test_host_player_name_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            with patch("app.preferences.settings_path", return_value=path):
                save_host_player_name("  Vicksauce  ")
                self.assertEqual(load_host_player_name(), "Vicksauce")

            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["host_player_name"], "Vicksauce")

    def test_known_player_names_remember_the_last_character(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            with patch("app.preferences.settings_path", return_value=path):
                save_last_player_name("Gorid")
                save_last_player_name("Vicksauce")
                names = load_known_player_names()
            self.assertEqual(names[0], "Vicksauce")
            self.assertIn("Gorid", names)

    def test_voice_defaults_on_and_can_be_turned_off(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            with patch("app.preferences.settings_path", return_value=path):
                self.assertTrue(load_voice_enabled())
                save_voice_enabled(False)
                self.assertFalse(load_voice_enabled())
                save_voice_enabled(True)
                self.assertTrue(load_voice_enabled())

    def test_ptt_binding_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            with patch("app.preferences.settings_path", return_value=path):
                self.assertEqual(load_ptt_binding()["code"], "Space")
                save_ptt_binding({"kind": "keyboard", "code": "KeyV", "label": "V"})
                self.assertEqual(load_ptt_binding()["code"], "KeyV")
                save_ptt_binding({"kind": "keyboard", "code": "??", "label": "x"})
                self.assertEqual(load_ptt_binding()["code"], "Space")


@unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
class ProtectedSecretTests(unittest.TestCase):
    def test_character_password_round_trips_without_plaintext_storage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            secret = "a-very-private-character-password-1234567890"
            with patch("app.preferences.settings_path", return_value=path):
                save_character_password("Vicksauce", secret)
                loaded = load_character_password("Vicksauce")

            raw = path.read_text(encoding="utf-8")
            self.assertNotIn(secret, raw)
            self.assertEqual(loaded, secret)
            self.assertIn("vicksauce", json.loads(raw)["character_passwords"])


if __name__ == "__main__":
    unittest.main()
