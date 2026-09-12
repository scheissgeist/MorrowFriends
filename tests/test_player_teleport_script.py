from pathlib import Path
import tempfile
import unittest

from app.config import install_roster_script


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "tes3mp_custom_scripts"
    / "morrowfriends_player_teleport.lua"
)


class PlayerTeleportScriptTests(unittest.TestCase):
    def test_installer_copies_and_requires_script_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "server" / "scripts"
            scripts.mkdir(parents=True)
            loader = scripts / "customScripts.lua"
            loader.write_text("-- custom scripts\n", encoding="utf-8")

            install_roster_script(root)
            install_roster_script(root)

            installed = scripts / "custom" / "morrowfriends_player_teleport.lua"
            self.assertEqual(installed.read_text(encoding="utf-8"), SCRIPT.read_text(encoding="utf-8"))
            loader_text = loader.read_text(encoding="utf-8")
            self.assertEqual(loader_text.count('require("custom/morrowfriends_player_teleport")'), 1)

    def test_every_alias_moves_only_the_requesting_player(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("logicHandler.TeleportToPlayer(pid, pid, targetPid)", source)
        self.assertNotIn("logicHandler.TeleportToPlayer(pid, cmd[", source)
        for command in ("goto", "tpto", "teleportto"):
            self.assertIn(
                f'customCommandHooks.registerCommand("{command}", teleportSelfToPlayer)',
                source,
            )

    def test_names_with_spaces_and_numeric_pids_are_supported(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("tonumber(target)", source)
        self.assertIn("tableHelper.concatenateFromIndex(cmd, 2)", source)
        self.assertIn("string.lower(accountName) == wanted", source)

    def test_teleports_have_a_short_spam_cooldown(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn("local TELEPORT_COOLDOWN_MS = time.seconds(2)", source)
        self.assertIn("lastTeleportAtMsByAccount", source)

    def test_loading_script_writes_a_verifiable_status_marker(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('jsonInterface.quicksave("player_teleport_status.json"', source)
        self.assertIn("Self teleport enabled: use /goto", source)


if __name__ == "__main__":
    unittest.main()
