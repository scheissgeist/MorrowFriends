"""Web admin panel: rules, player records, and the auth gate.

The panel exists because the desktop launcher cannot run a public server — the
TES3MP process is a CHILD of the launcher and died with it on 2026-08-18.
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "panel"))

from coop_rules import RULE_KEYS, read_rules, set_rule  # noqa: E402
from players import (  # noqa: E402
    broken_accounts,
    clear_expulsions,
    list_players,
    reset_password,
    set_staff_rank,
)

CONFIG_LUA = """
config = {}
config.shareJournal = true
config.shareBounty = false
config.shareTopics = true
config.bountyResetOnDeath = false
"""


def _config() -> Path:
    path = Path(tempfile.mkdtemp()) / "config.lua"
    path.write_text(CONFIG_LUA, encoding="utf-8")
    return path


def _data_root(records: dict[str, dict]) -> Path:
    root = Path(tempfile.mkdtemp())
    folder = root / "player"
    folder.mkdir(parents=True)
    for name, record in records.items():
        (folder / f"{name}.json").write_text(json.dumps(record), encoding="utf-8")
    return root


class RuleTests(unittest.TestCase):
    def test_reads_current_values(self):
        values = read_rules(_config())
        self.assertIs(values["shareJournal"], True)
        self.assertIs(values["shareBounty"], False)

    def test_bounty_is_unshared_by_default(self):
        """OFF means only the criminal is wanted — guards do not hunt the party."""
        self.assertIs(read_rules(_config())["shareBounty"], False)

    def test_toggle_is_confirmed_by_reading_back(self):
        path = _config()
        self.assertTrue(set_rule(path, "shareBounty", True))
        self.assertIs(read_rules(path)["shareBounty"], True)

    def test_missing_key_is_appended_not_silently_dropped(self):
        path = _config()
        self.assertNotIn("shareReputation", read_rules(path))
        self.assertTrue(set_rule(path, "shareReputation", True))
        self.assertIs(read_rules(path)["shareReputation"], True)

    def test_unknown_rule_is_refused(self):
        with self.assertRaises(ValueError):
            set_rule(_config(), "shareEverything", True)

    def test_every_declared_rule_is_settable(self):
        path = _config()
        for key in RULE_KEYS:
            self.assertTrue(set_rule(path, key, True), key)


class PlayerTests(unittest.TestCase):
    def test_lists_rank_and_console(self):
        root = _data_root({
            "Gorid": {"settings": {"staffRank": 3, "consoleAllowed": True},
                      "login": {"passwordHash": "a", "passwordSalt": "b"}},
            "Chwaest": {"settings": {}, "login": {"passwordHash": "a", "passwordSalt": "b"}},
        })
        rows = {row.name: row for row in list_players(root)}
        self.assertEqual(rows["Gorid"].staff_rank, 3)
        self.assertTrue(rows["Gorid"].console_allowed)
        self.assertEqual(rows["Chwaest"].staff_rank, 0)

    def test_credential_less_account_is_flagged_as_crashing(self):
        root = _data_root({"Retty": {"login": {"name": "Retty"}}})
        self.assertEqual(broken_accounts(root), ["Retty"])

    def test_demote_is_confirmed(self):
        root = _data_root({
            "Vicksauce": {"settings": {"staffRank": 3, "consoleAllowed": True},
                          "login": {"passwordHash": "a", "passwordSalt": "b"}},
        })
        self.assertTrue(set_staff_rank(root, "Vicksauce", 0, False))
        row = {r.name: r for r in list_players(root)}["Vicksauce"]
        self.assertEqual(row.staff_rank, 0)
        self.assertFalse(row.console_allowed)

    def test_password_reset_fixes_a_crashing_account(self):
        root = _data_root({"Retty": {"login": {"name": "Retty"}}})
        self.assertTrue(reset_password(root, "Retty", "morrowind"))
        self.assertEqual(broken_accounts(root), [])

    def test_password_reset_refuses_to_blank_credentials(self):
        """Clearing them does not trigger re-registration; it crashes the server."""
        root = _data_root({"Retty": {"login": {"passwordHash": "a", "passwordSalt": "b"}}})
        with self.assertRaises(ValueError):
            reset_password(root, "Retty", "")

    def test_password_reset_preserves_character_progress(self):
        root = _data_root({
            "Retty": {"login": {"name": "Retty"}, "inventory": [1, 2, 3], "skills": [1] * 27},
        })
        reset_password(root, "Retty", "morrowind")
        record = json.loads((root / "player" / "Retty.json").read_text(encoding="utf-8"))
        self.assertEqual(record["inventory"], [1, 2, 3])
        self.assertEqual(len(record["skills"]), 27)


class ExpulsionTests(unittest.TestCase):
    def test_reports_who_is_expelled(self):
        root = _data_root({
            "Vicksauce": {"factionExpulsion": {"mages guild": True}},
            # CoreScripts writes an empty Lua table as a JSON ARRAY, not {}.
            "Gorid": {"factionExpulsion": []},
        })
        rows = {row.name: row for row in list_players(root)}
        self.assertEqual(rows["Vicksauce"].expelled_from, ("mages guild",))
        self.assertEqual(rows["Gorid"].expelled_from, ())

    def test_clearing_sets_false_rather_than_deleting_the_entry(self):
        """LoadFactionExpulsion sends only the entries it finds.

        A deleted entry transmits nothing, so the client goes on believing it is
        expelled — the same shape as blanking credentials instead of resetting.
        """
        root = _data_root({"Vicksauce": {"factionExpulsion": {"mages guild": True}}})
        self.assertTrue(clear_expulsions(root, "Vicksauce"))

        record = json.loads(
            (root / "player" / "Vicksauce.json").read_text(encoding="utf-8")
        )
        self.assertIn("mages guild", record["factionExpulsion"])
        self.assertIs(record["factionExpulsion"]["mages guild"], False)

    def test_clearing_is_idempotent(self):
        root = _data_root({"Vicksauce": {"factionExpulsion": {"mages guild": True}}})
        self.assertTrue(clear_expulsions(root, "Vicksauce"))
        self.assertTrue(clear_expulsions(root, "Vicksauce"))
        self.assertEqual(list_players(root)[0].expelled_from, ())

    def test_clearing_preserves_character_progress(self):
        root = _data_root({
            "Vicksauce": {
                "factionExpulsion": {"mages guild": True},
                "inventory": [1, 2, 3],
                "skills": [1] * 27,
            },
        })
        clear_expulsions(root, "Vicksauce")
        record = json.loads(
            (root / "player" / "Vicksauce.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["inventory"], [1, 2, 3])
        self.assertEqual(len(record["skills"]), 27)

    def test_unknown_player_is_reported_not_silently_ok(self):
        self.assertFalse(clear_expulsions(_data_root({}), "Nobody"))


def _load_panel_app():
    """Load panel/app.py by PATH, not by name.

    `import app` collides with the launcher's own `app/` package — which one
    wins depends on sys.path order, so these tests passed alone and failed in
    the full suite. Load the file explicitly under a distinct module name.
    """
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "panel" / "app.py"
    spec = importlib.util.spec_from_file_location("morrowfriends_panel_app", path)
    module = importlib.util.module_from_spec(spec)
    # Register before executing. Flask resolves its root_path — and therefore
    # the templates folder — through sys.modules[import_name].__file__, so a
    # module still absent from sys.modules gets the CWD instead and every
    # render fails with TemplateNotFound.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AuthTests(unittest.TestCase):
    def test_blank_panel_password_locks_everyone_out(self):
        """An unset password must never mean 'anyone gets in'."""
        panel_app = _load_panel_app()
        panel_app.PANEL_PASS = ""
        self.assertFalse(panel_app.check_auth("admin", ""))
        self.assertFalse(panel_app.check_auth("admin", "anything"))

    def test_correct_credentials_pass(self):
        panel_app = _load_panel_app()
        panel_app.PANEL_USER = "admin"
        panel_app.PANEL_PASS = "s3cret"
        self.assertTrue(panel_app.check_auth("admin", "s3cret"))
        self.assertFalse(panel_app.check_auth("admin", "wrong"))


class ExpulsionRoutingTests(unittest.TestCase):
    """A connected player must be fixed in game, not in their saved file.

    The server holds faction state in memory and rewrites the record on its next
    save, so editing the file of someone who is logged in is silently discarded.
    """

    def _client(self, records: dict[str, dict], online: list[dict]):
        panel_app = _load_panel_app()
        root = _data_root(records)
        (root / "live_players.json").write_text(
            json.dumps({"version": 1, "players": online}), encoding="utf-8"
        )
        panel_app.DATA_ROOT = root
        panel_app.PANEL_USER = "admin"
        panel_app.PANEL_PASS = "s3cret"
        panel_app.app.config["TESTING"] = True
        return panel_app.app.test_client(), root

    @staticmethod
    def _auth() -> dict[str, str]:
        token = base64.b64encode(b"admin:s3cret").decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def test_offline_player_is_fixed_in_their_saved_record(self):
        client, root = self._client(
            {"Vicksauce": {"factionExpulsion": {"mages guild": True}}}, online=[]
        )
        body = client.post(
            "/api/player/expulsion", json={"name": "Vicksauce"}, headers=self._auth()
        ).get_json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["route"], "file")
        self.assertEqual(list_players(root)[0].expelled_from, ())

    def test_connected_player_is_queued_and_their_file_is_left_alone(self):
        client, root = self._client(
            {"Vicksauce": {"factionExpulsion": {"mages guild": True}}},
            online=[{"name": "Vicksauce", "cell": "Ulummusa"}],
        )
        body = client.post(
            "/api/player/expulsion", json={"name": "Vicksauce"}, headers=self._auth()
        ).get_json()

        self.assertEqual(body["route"], "queued")
        command = json.loads(
            (root / "host_commands.json").read_text(encoding="utf-8")
        )
        self.assertEqual(command["action"], "clear_expulsion")
        self.assertEqual(command["target"], "Vicksauce")
        # Untouched: the running server owns this record right now.
        self.assertEqual(list_players(root)[0].expelled_from, ("mages guild",))

    def test_connected_player_is_recognised_despite_different_name_case(self):
        """Panel lookups remain case-insensitive for typed account names."""
        client, root = self._client(
            {"Artyom": {"factionExpulsion": {"mages guild": True}}},
            online=[{"name": "artyom", "cell": "Ulummusa"}],
        )
        body = client.post(
            "/api/player/expulsion", json={"name": "Artyom"}, headers=self._auth()
        ).get_json()

        self.assertEqual(body["route"], "queued")
        self.assertEqual(list_players(root)[0].expelled_from, ("mages guild",))

    def test_ban_queues_a_server_side_account_and_ip_ban(self):
        client, root = self._client({}, online=[{"name": "Artyom", "cell": "Balmora"}])
        response = client.post(
            "/api/player/ban", json={"name": "Artyom"}, headers=self._auth()
        )

        self.assertEqual(response.status_code, 200)
        command = json.loads(
            (root / "host_commands.json").read_text(encoding="utf-8")
        )
        self.assertEqual(command, {"action": "ban", "target": "Artyom"})

    def test_clear_all_sweeps_offline_records_and_queues_one_command(self):
        client, root = self._client(
            {
                "Vicksauce": {"factionExpulsion": {"mages guild": True}},
                "Handini": {"factionExpulsion": {"fighters guild": True}},
                "Artyom": {"factionExpulsion": {"thieves guild": True}},
            },
            online=[{"name": "artyom", "cell": "Ulummusa"}],
        )
        body = client.post(
            "/api/expulsion/clear-all", json={}, headers=self._auth()
        ).get_json()

        self.assertTrue(body["ok"])
        self.assertEqual(sorted(body["cleared"]), ["Handini", "Vicksauce"])

        rows = {row.name: row for row in list_players(root)}
        self.assertEqual(rows["Vicksauce"].expelled_from, ())
        self.assertEqual(rows["Handini"].expelled_from, ())
        # The connected one is left to the queued sweep.
        self.assertEqual(rows["Artyom"].expelled_from, ("thieves guild",))

        command = json.loads(
            (root / "host_commands.json").read_text(encoding="utf-8")
        )
        self.assertEqual(command["action"], "clear_expulsion")
        # No target means every connected player, in ONE command: the queue
        # holds a single entry, so per-player commands would overwrite each other.
        self.assertNotIn("target", command)

    def test_dashboard_renders_the_guild_section(self):
        """A template error here takes down the whole admin page, not one panel."""
        client, _ = self._client(
            {
                "Vicksauce": {"factionExpulsion": {"mages guild": True},
                              "login": {"passwordHash": "a", "passwordSalt": "b"}},
                "Gorid": {"factionExpulsion": [],
                          "login": {"passwordHash": "a", "passwordSalt": "b"}},
            },
            online=[],
        )
        page = client.get("/", headers=self._auth())
        self.assertEqual(page.status_code, 200)

        body = page.get_data(as_text=True)
        self.assertIn("Guild standing", body)
        self.assertIn("mages guild", body)

    def test_expulsion_route_requires_auth(self):
        client, _ = self._client({}, online=[])
        self.assertEqual(client.post("/api/player/expulsion", json={}).status_code, 401)
        self.assertEqual(client.post("/api/expulsion/clear-all", json={}).status_code, 401)
        self.assertEqual(client.post("/api/player/ban", json={}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
