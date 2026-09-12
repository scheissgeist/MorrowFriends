from pathlib import Path
import unittest


ROSTER_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "tes3mp_custom_scripts"
    / "morrowfriends_roster.lua"
)


class RosterScriptTests(unittest.TestCase):
    def test_gold_grant_restores_equipment_after_inventory_reload(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        give_gold = source.index('cmd.action == "give_gold"')
        load_inventory = source.index("Players[pid]:LoadInventory()", give_gold)
        load_equipment = source.index("Players[pid]:LoadEquipment()", give_gold)

        self.assertLess(load_inventory, load_equipment)

    def test_save_all_snapshots_players_before_acknowledgement(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        save_all = source.index("local function saveAllServerState()")
        command_runner = source.index("local function runHostCommand", save_all)
        save_body = source[save_all:command_runner]

        self.assertIn('player:SaveCell(packetReader.GetPlayerPacketTables(pid, "PlayerCellChange"))', save_body)
        self.assertIn(
            'player:SaveStatsDynamic(packetReader.GetPlayerPacketTables(pid, "PlayerStatsDynamic"))',
            save_body,
        )
        self.assertIn("player:SaveToDrive()", save_body)
        self.assertIn("WorldInstance:SaveToDrive()", save_body)

        run_command = source.index("pcall(runHostCommand, cmd)")
        write_result = source.index("jsonInterface.quicksave(RESULT_FILE, result)")
        self.assertLess(run_command, write_result)

    def test_voice_snapshot_contains_authoritative_pose_at_five_hertz(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")

        for api in (
            "tes3mp.GetCell(pid)",
            "tes3mp.IsInExterior(pid)",
            "tes3mp.GetPosX(pid)",
            "tes3mp.GetPosY(pid)",
            "tes3mp.GetPosZ(pid)",
            "tes3mp.GetRotX(pid)",
            "tes3mp.GetRotZ(pid)",
        ):
            self.assertIn(api, source)
        self.assertIn("local POSITION_SAMPLE_MS = 200", source)
        self.assertIn('"MorrowFriendsWritePositionSnapshot", POSITION_SAMPLE_MS', source)

    def test_voice_claim_is_private_random_and_short_lived(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        claim_start = source.index("local function issueVoiceClaim(pid, announce)")
        claim_end = source.index('customCommandHooks.registerCommand("voice"', claim_start)
        claim_body = source[claim_start:claim_end]

        self.assertIn("tes3mp.GenerateRandomString(16):upper()", claim_body)
        self.assertIn("expiresAtMs = issuedAt + VOICE_CLAIM_LIFETIME_MS", claim_body)
        self.assertIn("tes3mp.SendMessage(", claim_body)
        self.assertIn("false\n        )", claim_body)
        self.assertNotIn("LogMessage", claim_body)
        self.assertIn('customCommandHooks.registerCommand("voice"', source)
        self.assertIn("issuedVoiceFor[playerName] ~= true", source)
        self.assertIn("issueVoiceClaim(pid, true)", source)

    def test_a_spare_voice_claim_is_kept_minted_for_logged_in_players(self) -> None:
        """A claim is one-time-use, so login-only issuance stranded latecomers."""
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")

        # Renewal must be silent or chat gets a code every refresh interval.
        self.assertIn("elseif not voiceClaimIsFresh(playerName) then", source)
        self.assertIn("issueVoiceClaim(pid, false)", source)
        self.assertIn("local VOICE_CLAIM_REFRESH_MS = time.minutes(1)", source)

        fresh_start = source.index("local function voiceClaimIsFresh(playerName)")
        fresh_body = source[fresh_start:source.index("local function issueVoiceClaim", fresh_start)]
        self.assertIn("claim.expiresAtMs > now", fresh_body)
        self.assertIn("(now - claim.issuedAtMs) < VOICE_CLAIM_REFRESH_MS", fresh_body)

    def test_claim_lifetime_stays_within_the_relay_cap(self) -> None:
        """core.py rejects the whole claims message above MAX_CLAIM_LIFETIME_MS."""
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("local VOICE_CLAIM_LIFETIME_MS = time.minutes(5)", source)

    def test_login_does_not_print_a_voice_code_in_chat(self) -> None:
        """A printed code is unusable: Morrowind's chat is not selectable text.

        The page redeems a claim by NAME within seconds, so nothing needs to be
        read off the screen. Recovery is the launcher Voice button, not a chat
        code. /voice still exists for the rare join-code fallback.
        """
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        start = source.index("if issuedVoiceFor[playerName] ~= true then")
        login_body = source[start:source.index("elseif not voiceClaimIsFresh", start)]

        self.assertIn("issueVoiceClaim(pid, false)", login_body)
        self.assertNotIn("issueVoiceClaim(pid, true)", login_body)
        self.assertNotIn("Voice setup code", login_body)
        self.assertNotIn("Type /voice if it does not connect", login_body)
        self.assertIn("open Voice in MorrowFriends.", login_body)
        self.assertNotIn("pick your name", login_body)

    def test_the_code_is_still_available_on_demand(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        command = source.index('customCommandHooks.registerCommand("voice"')

        self.assertIn("issueVoiceClaim(pid, true)", source[command:command + 200])
        self.assertIn("Voice setup code: ", source)

    def test_selected_host_gets_owner_rank_and_console_immediately(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        action = source.index('cmd.action == "grant_host_owner"')
        body = source[action:source.index("function MorrowFriendsPollCommands", action)]

        self.assertIn("Players[pid].data.settings.staffRank = 3", body)
        self.assertIn("Players[pid].data.settings.consoleAllowed = true", body)
        self.assertIn("Players[pid]:QuicksaveToDrive()", body)
        self.assertIn("Players[pid]:LoadSettings()", body)

    def _clear_expulsion_body(self) -> str:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        action = source.index('cmd.action == "clear_expulsion"')
        return source[action:source.index("function MorrowFriendsPollCommands", action)]

    def test_lifting_an_expulsion_sets_false_rather_than_removing_the_entry(self) -> None:
        """A removed entry is never transmitted, so the client stays expelled.

        StateHelper:LoadFactionExpulsion iterates pairs(factionExpulsion) and
        sends only the entries it finds — the same trap as blanking credentials
        instead of resetting them.
        """
        body = self._clear_expulsion_body()

        self.assertIn("expulsion[factionId] = false", body)
        self.assertNotIn("expulsion[factionId] = nil", body)

    def test_lifting_an_expulsion_persists_before_pushing_to_the_client(self) -> None:
        body = self._clear_expulsion_body()

        self.assertLess(
            body.index("player:QuicksaveToDrive()"),
            body.index("player:LoadFactionExpulsion()"),
        )

    def test_expulsion_target_is_matched_case_insensitively(self) -> None:
        """Host command targets are typed by hand, so case will not line up with
        the account name the saved record is keyed by."""
        self.assertIn("playerAnswersTo(pid, player, cmd.target)", self._clear_expulsion_body())


class PlayerIdentityTests(unittest.TestCase):
    """A player's identity is their ACCOUNT name, never their character name.

    TES3MP lets the two diverge freely: on 2026-08-22 an account named "Guard"
    was playing a character called "rottencheeseCA", so a roster built from
    tes3mp.GetName listed rottencheeseCA twice and Guard not at all. Guard's
    login then consumed the voice claim minted under "rottencheeseCA", leaving
    the real rottencheeseCA with none and his auto-claim returning 400 forever.
    """

    def setUp(self) -> None:
        self.source = ROSTER_SCRIPT.read_text(encoding="utf-8")

    def _body(self, start: str, end: str) -> str:
        begin = self.source.index(start)
        return self.source[begin:self.source.index(end, begin)]

    def test_the_published_roster_uses_the_account_name(self) -> None:
        body = self._body("local function writeRoster()", "local function findPidByName")

        self.assertIn("local playerName = accountNameFor(pid)", body)
        self.assertNotIn("tes3mp.GetName(pid)", body)

    def test_voice_claims_are_minted_against_the_account_name(self) -> None:
        body = self._body(
            "local function issueVoiceClaim(pid, announce)",
            'customCommandHooks.registerCommand("voice"',
        )

        self.assertIn("local playerName = accountNameFor(pid)", body)
        self.assertNotIn("tes3mp.GetName(pid)", body)

    def test_the_claim_is_released_under_the_same_name_it_was_taken(self) -> None:
        """Releasing under a different key leaks the issuedVoiceFor entry, and
        the account can then never mint another claim for the whole session."""
        body = self._body(
            'customEventHooks.registerHandler("OnPlayerDisconnect"',
            'customEventHooks.registerHandler("OnServerPostInit"',
        )

        self.assertIn("local playerName = accountNameFor(pid)", body)
        self.assertIn("issuedVoiceFor[playerName] = nil", body)

    def test_account_name_falls_back_only_when_it_is_missing(self) -> None:
        body = self._body("local function accountNameFor(pid)", "local function writeVoiceClaims")

        self.assertIn("player.accountName", body)
        # The fallback exists for the pre-login window only, and must come after
        # the account name, never instead of it.
        self.assertLess(body.index("player.accountName"), body.index("tes3mp.GetName(pid)"))

    def test_owner_rank_never_matches_a_player_chosen_name(self) -> None:
        """Owner rank grants staff rank 3 and the console.

        accountNameFor() falls back to the character name, which players pick
        themselves, so matching on it would hand the console to anyone who named
        their character after the owner.
        """
        start = self.source.index("if issuedVoiceFor[playerName] ~= true then")
        body = self.source[start:self.source.index("elseif not voiceClaimIsFresh", start)]

        self.assertIn("local ownerAccount = Players[pid].accountName", body)
        self.assertIn("string.lower(ownerAccount) == string.lower(OWNER_NAME)", body)
        self.assertNotIn("string.lower(playerName) == string.lower(OWNER_NAME)", body)
        self.assertNotIn("accountNameFor(pid)) == string.lower(OWNER_NAME)", body)

    def test_host_commands_resolve_targets_by_account_only(self) -> None:
        """findPidByName picks the target for kick, teleport and
        grant_host_owner. Honouring the character name would let anyone claim a
        command aimed at someone else by renaming their character."""
        body = self._body("local function findPidByName(name)", "-- Case-insensitive identity check")

        self.assertIn("player.accountName", body)
        self.assertNotIn("tes3mp.GetName", body)
        # Typed by hand into the panel, so case will not match the record.
        self.assertIn("string.lower", body)

    def test_ban_uses_corescripts_persistence_then_normal_player_cleanup(self) -> None:
        body = self._body('elseif cmd.action == "ban"', 'elseif cmd.action == "teleport_to_host"')

        self.assertIn("logicHandler.BanPlayer", body)
        self.assertIn("Players[pid].accountName", body)
        self.assertIn("Players[pid]:Kick()", body)

    def test_goto_still_accepts_the_name_shown_above_a_players_head(self) -> None:
        """The roster shows account names but the game world shows character
        names, so a player may reasonably type either into /goto."""
        body = self._body('customCommandHooks.registerCommand("goto"', "local function writeRoster()")

        self.assertIn("accountNameFor(otherPid)", body)
        self.assertIn("tes3mp.GetName(otherPid)", body)


class RegistrationGateTests(unittest.TestCase):
    """Anyone who can reach the server can connect. That is a product decision.

    Open registration and the absence of an allow list are intentional.
    """

    def test_there_is_no_connect_validator_and_no_allow_list(self) -> None:
        source = ROSTER_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('registerValidator("OnPlayerConnect"', source)
        self.assertNotIn("allow_register", source)
        self.assertNotIn("ALLOWED_ACCOUNTS_FILE", source)
        self.assertNotIn("Refused new account", source)


if __name__ == "__main__":
    unittest.main()
