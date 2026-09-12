"""Positional voice needs every link alive; name the one that is down.

On 2026-08-18 "voice doesn't work" was reported four times and looked identical
each time, while the broken link differed: the game server had crashed, the
launcher had been closed, a media connection failed after a successful claim,
and once the page claimed the HOST's identity for a friend.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.voice_chain import (
    RELAY_STALE_SECONDS,
    check_claims,
    check_game_feed,
    check_relay,
    diagnose,
)


def _root_with(snapshot: dict | None, claims: dict | None = None, age: float = 0.0) -> Path:
    root = Path(tempfile.mkdtemp())
    data = root / "server" / "data"
    data.mkdir(parents=True)
    if snapshot is not None:
        path = data / "live_players.json"
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        if age:
            old = time.time() - age
            import os

            os.utime(path, (old, old))
    if claims is not None:
        (data / "voice_claims.json").write_text(json.dumps(claims), encoding="utf-8")
    return root


LIVE = {"version": 1, "sequence": 5, "players": [{"name": "Gorid", "cell": "Balmora"}]}


class GameFeedTests(unittest.TestCase):
    def test_missing_file_is_named(self):
        status = check_game_feed(_root_with(None))
        self.assertFalse(status.ok)
        self.assertIn("no position file", status.detail)

    def test_unversioned_payload_is_named(self):
        # The old OnServerExit handler wrote a bare {}. The relay bridge
        # refuses to publish it, so the relay receives nothing at all.
        status = check_game_feed(_root_with({}))
        self.assertFalse(status.ok)

    def test_stale_feed_is_named_with_the_relay_threshold(self):
        status = check_game_feed(_root_with(LIVE, age=RELAY_STALE_SECONDS + 30))
        self.assertFalse(status.ok)
        self.assertIn("old", status.detail)

    def test_fresh_feed_with_players_passes(self):
        status = check_game_feed(_root_with(LIVE))
        self.assertTrue(status.ok)
        self.assertIn("1 player", status.detail)

    def test_empty_but_fresh_feed_is_not_a_failure(self):
        status = check_game_feed(_root_with({"version": 1, "sequence": 2, "players": []}))
        self.assertTrue(status.ok)


class ClaimTests(unittest.TestCase):
    def test_claims_list_the_known_characters(self):
        root = _root_with(LIVE, claims={"version": 1, "claims": {"AAAA": {"player": "Gorid"}}})
        status = check_claims(root)
        self.assertTrue(status.ok)
        self.assertIn("Gorid", status.detail)

    def test_no_claims_yet_is_not_a_failure(self):
        status = check_claims(_root_with(LIVE, claims={"version": 1, "claims": {}}))
        self.assertTrue(status.ok)


class RelayTests(unittest.TestCase):
    def _with_health(self, payload):
        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return json.dumps(payload).encode("utf-8")

        return patch("app.voice_chain.urllib.request.urlopen", return_value=_Resp())

    def test_host_offline_blames_the_launcher_uplink(self):
        with self._with_health({"ok": True, "party": "p", "host_online": False, "names": []}):
            status = check_relay("https://voice.example", "p")
        self.assertFalse(status.ok)
        self.assertIn("launcher", status.detail)

    def test_healthy_relay_reports_player_count(self):
        with self._with_health({"ok": True, "party": "p", "host_online": True, "names": ["a", "b"]}):
            status = check_relay("https://voice.example", "p")
        self.assertTrue(status.ok)
        self.assertIn("2 player", status.detail)

    def test_wrong_party_is_named(self):
        with self._with_health({"ok": True, "party": "other", "host_online": True, "names": []}):
            status = check_relay("https://voice.example", "p")
        self.assertFalse(status.ok)

    def test_unreachable_relay_is_named_not_raised(self):
        with patch("app.voice_chain.urllib.request.urlopen", side_effect=OSError("boom")):
            status = check_relay("https://voice.example", "p")
        self.assertFalse(status.ok)
        self.assertIn("unreachable", status.detail)


class DiagnoseTests(unittest.TestCase):
    def test_summary_names_the_first_broken_link(self):
        root = _root_with(None)
        with patch("app.voice_chain.urllib.request.urlopen", side_effect=OSError("x")):
            report = diagnose(root, "https://voice.example", "p")
        self.assertFalse(report.ok)
        self.assertEqual(report.first_broken.name, "Game feed")
        self.assertIn("Game feed", report.summary())


if __name__ == "__main__":
    unittest.main()
