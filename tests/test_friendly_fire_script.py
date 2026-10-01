from pathlib import Path
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "packaging" / "tes3mp_custom_scripts"
FRIENDLY_FIRE_SCRIPT = SCRIPTS / "morrowfriends_friendly_fire.lua"


class FriendlyFireScriptTests(unittest.TestCase):
    """Fighting each other must not leave the group hunted by every town guard.

    Bounties are decided client-side and reported to the server with no cause
    attached, so the only lever is to notice that a player was mid-brawl and
    refuse the increase that follows.
    """

    def setUp(self) -> None:
        self.source = FRIENDLY_FIRE_SCRIPT.read_text(encoding="utf-8")

    def _validator_body(self) -> str:
        start = self.source.index('customEventHooks.registerValidator("OnPlayerBounty"')
        return self.source[start:self.source.index(
            'customEventHooks.registerHandler("OnPlayerDisconnect"', start
        )]

    def test_the_bounty_is_intercepted_before_it_is_ever_persisted(self) -> None:
        """It has to be a VALIDATOR, not a handler.

        eventHandler.OnPlayerBounty saves the new figure in its default handler,
        which runs after validators. A validator still sees the old saved bounty
        in Players[pid].data.fame.bounty, which is the value to restore; by the
        time a handler runs, that record already holds the bad number.
        """
        self.assertIn('customEventHooks.registerValidator("OnPlayerBounty"', self.source)
        self.assertNotIn('customEventHooks.registerHandler("OnPlayerBounty"', self.source)

    def test_a_rejected_bounty_is_pushed_back_to_the_client(self) -> None:
        """Blocking the save alone would leave the client showing the bounty and
        guards on that client still hostile."""
        body = self._validator_body()

        self.assertIn("tes3mp.SetBounty(pid, saved)", body)
        self.assertIn("tes3mp.SendBounty(pid)", body)
        self.assertLess(body.index("tes3mp.SetBounty"), body.index("tes3mp.SendBounty"))

    def test_rejecting_skips_only_the_default_handler(self) -> None:
        """makeEventStatus(false, true): other scripts' handlers still run."""
        self.assertIn(
            "return customEventHooks.makeEventStatus(false, true)", self._validator_body()
        )

    def test_paying_a_fine_is_never_blocked(self) -> None:
        """Only increases are suppressed. Serving time or paying off a bounty
        lowers it, and swallowing that would trap the player at their bounty."""
        self.assertIn("if incoming <= saved or not isBrawling(pid) then", self._validator_body())

    def test_ordinary_crime_away_from_a_fight_is_untouched(self) -> None:
        body = self._validator_body()
        # The brawl window is the whole gate; without it this would erase every
        # bounty on the server and make crime meaningless.
        self.assertIn("isBrawling(pid)", body)
        self.assertIn("local PVP_GRACE_MS = time.seconds(10)", self.source)

    def test_the_attacker_is_marked_not_the_packet_sender(self) -> None:
        """The cell authority forwards hits on behalf of other players, so the
        pid that sent the packet is often not the pid that swung."""
        start = self.source.index('customEventHooks.registerHandler("OnObjectHit"')
        body = self.source[start:self.source.index(
            'customEventHooks.registerHandler("OnPlayerDeath"', start
        )]

        self.assertIn("local hittingPid = targetPlayer.hittingPid", body)
        self.assertIn("markPlayerCombat(hittingPid)", body)
        self.assertNotIn("markPlayerCombat(pid)", body)
        # Self-damage earns nobody a bounty and must not open the window.
        self.assertIn("hittingPid ~= targetPid", body)

    def test_a_kill_by_spell_or_summon_still_counts_as_a_brawl(self) -> None:
        """OnObjectHit only covers direct hits. A player killed by a spell,
        a summon or a shove off a ledge produces no hit from the killer, so the
        death itself has to open the window or the murder bounty sticks."""
        start = self.source.index('customEventHooks.registerHandler("OnPlayerDeath"')
        body = self.source[start:self.source.index(
            'customEventHooks.registerValidator("OnPlayerBounty"', start
        )]

        self.assertIn("tes3mp.DoesPlayerHavePlayerKiller(pid)", body)
        self.assertIn("tes3mp.GetPlayerKillerPid(pid)", body)
        self.assertIn("markPlayerCombat(killerPid)", body)
        self.assertIn("killerPid ~= pid", body)

    def test_the_window_is_dropped_when_a_player_leaves(self) -> None:
        """pids are recycled, so a stale entry would forgive the next player to
        take that slot a bounty they earned honestly."""
        self.assertIn("pvpUntilMs[pid] = nil", self.source)


class FriendlyFireInstallTests(unittest.TestCase):
    def test_the_script_is_installed_and_required_like_the_others(self) -> None:
        config = (Path(__file__).resolve().parents[1] / "app" / "config.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('FRIENDLY_FIRE_SCRIPT_NAME = "morrowfriends_friendly_fire.lua"', config)
        self.assertIn('require("custom/morrowfriends_friendly_fire")', config)
        self.assertIn("custom/morrowfriends_friendly_fire", config)

    def test_the_release_build_ships_the_script(self) -> None:
        """The released app installs the script from packaging/tes3mp_custom_scripts
        beside app/, so a script the build does not copy silently never installs."""
        packaging = Path(__file__).resolve().parents[1] / "packaging"
        build = (packaging / "build_portable.ps1").read_text(encoding="utf-8")

        self.assertTrue(
            (packaging / "tes3mp_custom_scripts" / "morrowfriends_friendly_fire.lua").is_file()
        )
        self.assertIn(r'Copy-Item "packaging\tes3mp_custom_scripts\*.lua"', build)


if __name__ == "__main__":
    unittest.main()
