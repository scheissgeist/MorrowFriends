import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.voice_client import (
    DEFAULT_VOICE_PARTY,
    friend_voice_url,
    load_voice_client_config,
    open_voice_client,
)


class VoiceClientTests(unittest.TestCase):
    def test_default_join_url_uses_shipped_party(self) -> None:
        url = friend_voice_url()
        self.assertTrue(url.startswith("https://voice.gamebrain.win/"))
        self.assertIn(f"party={DEFAULT_VOICE_PARTY}", url)

    def test_shipped_config_file_can_supply_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MorrowFriends.voice.json"
            path.write_text(
                json.dumps(
                    {
                        "allowed_origins": ["https://voice.example.test"],
                        "default_page": "https://voice.example.test/",
                        "default_party": "custom-party",
                    }
                ),
                encoding="utf-8",
            )
            with patch(
                "app.voice_client.voice_config_candidates", return_value=[path]
            ):
                config = load_voice_client_config()
        self.assertEqual(config.party_id, "custom-party")
        self.assertEqual(
            config.join_url, "https://voice.example.test/?party=custom-party"
        )

    def test_open_falls_back_to_the_browser_when_edge_is_missing(self) -> None:
        with (
            patch("app.voice_client._open_edge_app", return_value=False),
            patch("app.voice_client._open_system_browser", return_value=True) as browser,
        ):
            launch = open_voice_client()
        self.assertTrue(launch.ok)
        self.assertEqual(launch.method, "browser")
        browser.assert_called_once()
        self.assertIn("party=", launch.url)

    def test_opening_never_claims_success_without_opening_something(self) -> None:
        """The pywebview branch used to return True the moment it spawned a
        thread that then died on 'must be run on a main thread', so the first
        click reported success and opened nothing."""
        with (
            patch("app.voice_client._open_edge_app", return_value=False),
            patch("app.voice_client._open_system_browser", return_value=False),
        ):
            launch = open_voice_client()
        self.assertFalse(launch.ok)
        self.assertEqual(launch.method, "none")


if __name__ == "__main__":
    unittest.main()
