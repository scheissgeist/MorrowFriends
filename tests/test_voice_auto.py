import json
import tempfile
import unittest
from pathlib import Path

from app.voice_auto import (
    local_login_name,
    parse_local_login_name,
    pending_claim_code,
    scan_tes3mp_logs_for_claim,
    voice_join_url,
)


class VoiceAutoTests(unittest.TestCase):
    def test_pending_claim_matches_player_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "server" / "data"
            data.mkdir(parents=True)
            (data / "voice_claims.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "claims": {
                            "A1B2C3D4E5F6G7H8": {
                                "player": "Vicksauce",
                                "issuedAtMs": 1,
                                "expiresAtMs": 9,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(pending_claim_code("vicksauce", root), "A1B2C3D4E5F6G7H8")
            self.assertIsNone(pending_claim_code("Gorid", root))

    def test_log_scanner_reads_the_latest_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tes3mp.log").write_text(
                "hello\nVoice setup code: AAAABBBBCCCCDDDD\nVoice setup code: EEEEFFFFGGGGHHHH\n",
                encoding="utf-8",
            )
            self.assertEqual(scan_tes3mp_logs_for_claim(root), "EEEEFFFFGGGGHHHH")

    def test_join_url_includes_auto_player_and_code(self) -> None:
        url = voice_join_url(
            player="Vicksauce",
            code="A1B2C3D4E5F6G7H8",
            ptt={"kind": "keyboard", "code": "KeyV", "label": "V"},
        )
        self.assertIn("party=", url)
        self.assertIn("player=Vicksauce", url)
        self.assertIn("auto=1", url)
        self.assertIn("code=A1B2C3D4E5F6G7H8", url)
        self.assertIn("ptt_kind=keyboard", url)
        self.assertIn("ptt=KeyV", url)
        self.assertIn("ptt_label=V", url)

    def test_attach_voice_does_not_wait_for_a_local_claim_file(self) -> None:
        """Friend PCs do not have voice_claims.json. Waiting only delayed Play."""
        source = Path(__file__).resolve().parents[1] / "app" / "voice_auto.py"
        text = source.read_text(encoding="utf-8")
        start = text.index("def attach_voice")
        nxt = text.find("\ndef ", start + 1)
        body = text[start:nxt if nxt != -1 else None]
        self.assertNotIn("pending_claim_code", body)
        self.assertNotIn("scan_tes3mp_logs_for_claim", body)
        self.assertNotIn("time.sleep", body)
        self.assertIn("voice_join_url(player=player_name)", body)


class LocalLoginNameTests(unittest.TestCase):
    """Identity comes from THIS client's Welcome line, not the party list."""

    EXISTING = (
        "[2026-08-21 20:53:40] [INFO]: Gorid (0) has joined the server.\n"
        "\n"
        "[2026-08-21 20:53:40] [INFO]: ID_GUI_MESSAGEBOX, Type 3, MSG Enter your password:\n"
        "[2026-08-21 20:53:40] [INFO]: Welcome Gorid\n"
        "You have 60 seconds to log in.\n"
        "\n"
        "[2026-08-21 20:53:58] [INFO]: rottencheeseCA (2) has joined the server.\n"
        "[2026-08-21 20:53:58] [INFO]: Guard (1) has joined the server.\n"
        "[2026-08-21 19:18:00] [INFO]: #FFFFFFVicksauce (2): welcome to hell\n"
    )

    NEW_ACCOUNT = (
        "[2026-08-20 21:23:56] [INFO]:  Gorid (0) has joined the server.\n"
        "\n"
        "[2026-08-20 21:23:56] [INFO]: ID_GUI_MESSAGEBOX, Type 3, MSG Create new password:\n"
        "[2026-08-20 21:23:56] [INFO]: Welcome  Gorid\n"
        "You have 60 seconds to register.\n"
    )

    BUSY_BEFORE_US = (
        "[2026-08-21 19:14:13] [INFO]: Retarded Combine (0) has joined the server.\n"
        "[2026-08-21 19:14:16] [INFO]: Sending ID_PLAYER_BASEINFO to server with my CharGen info\n"
        "[2026-08-21 19:14:16] [INFO]: Gorid (1) has joined the server.\n"
        "[2026-08-21 19:14:16] [INFO]: Welcome Gorid\n"
        "You have 60 seconds to log in.\n"
        "[2026-08-21 19:14:21] [INFO]: Vicksauce (2) has joined the server.\n"
    )

    def test_existing_character_welcome(self) -> None:
        self.assertEqual(parse_local_login_name(self.EXISTING), "Gorid")

    def test_new_account_welcome_strips_the_leading_space(self) -> None:
        self.assertEqual(parse_local_login_name(self.NEW_ACCOUNT), "Gorid")

    def test_does_not_take_someone_who_was_already_there(self) -> None:
        self.assertEqual(parse_local_login_name(self.BUSY_BEFORE_US), "Gorid")

    def test_chat_saying_welcome_is_not_a_login(self) -> None:
        chat = (
            "[2026-08-21 19:17:56] [INFO]: #FFFFFFRetarded Combine (0): welcome to hell\n"
            "You have 60 seconds to log in.\n"
        )
        self.assertIsNone(parse_local_login_name(chat))

    def test_welcome_without_the_login_timer_is_ignored(self) -> None:
        self.assertIsNone(parse_local_login_name("[INFO]: Welcome Gorid\nHello there.\n"))

    def test_stale_logs_from_last_night_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "tes3mp-client-2026-08-20-21_07_16.log"
            log.write_text(self.EXISTING, encoding="utf-8")
            older = log.stat().st_mtime - 3600
            # Force an old mtime so a leftover session cannot name us.
            import os

            os.utime(log, (older, older))
            self.assertIsNone(local_login_name(since=older + 1800, directory=root))

    def test_this_session_log_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "tes3mp-client-2026-08-21-20_53_24.log"
            log.write_text(self.EXISTING, encoding="utf-8")
            self.assertEqual(
                local_login_name(since=log.stat().st_mtime - 1, directory=root),
                "Gorid",
            )


if __name__ == "__main__":
    unittest.main()
