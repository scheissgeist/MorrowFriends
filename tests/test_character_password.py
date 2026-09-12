"""A credential-less player record crashes the whole TES3MP server.

HasAccount() is true whenever the record file loads, so deleting
passwordHash/passwordSalt does NOT produce a fresh registration — the server
shows the LOGIN dialog and stock eventHandler.lua then evaluates

    local passwordSalt = Players[pid].data.login.passwordSalt   -- nil
    ... tes3mp.GetSHA256Hash(data .. passwordSalt)              -- concat nil

which errors inside a C++ callback and kills the process with ucrtbase
0xc0000409. On 2026-08-18 that produced five server crashes, every one of them
seconds after the same player tried to log in.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.engine import accounts_missing_credentials, reset_character_password


def _make_root() -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "server" / "data" / "player").mkdir(parents=True)
    return root


def _write(root: Path, name: str, login: dict) -> Path:
    path = root / "server" / "data" / "player" / f"{name}.json"
    path.write_text(
        json.dumps({"login": login, "inventory": [1, 2, 3], "skills": [1] * 27}),
        encoding="utf-8",
    )
    return path


class DetectCrashingAccountsTests(unittest.TestCase):
    def test_record_without_credentials_is_reported(self):
        root = _make_root()
        _write(root, "Retarded Combine", {"name": "Retarded Combine"})
        with patch("app.engine.tes3mp_dir", return_value=root):
            self.assertEqual(accounts_missing_credentials(), ["Retarded Combine"])

    def test_healthy_record_is_not_reported(self):
        root = _make_root()
        _write(root, "Gorid", {"name": "Gorid", "passwordHash": "a" * 64, "passwordSalt": "b" * 64})
        with patch("app.engine.tes3mp_dir", return_value=root):
            self.assertEqual(accounts_missing_credentials(), [])

    def test_empty_string_credentials_count_as_missing(self):
        root = _make_root()
        _write(root, "Broken", {"name": "Broken", "passwordHash": "", "passwordSalt": ""})
        with patch("app.engine.tes3mp_dir", return_value=root):
            self.assertEqual(accounts_missing_credentials(), ["Broken"])


class ResetPasswordTests(unittest.TestCase):
    def test_reset_writes_a_verifiable_salt_and_hash(self):
        root = _make_root()
        path = _write(root, "Retarded Combine", {"name": "Retarded Combine"})
        with patch("app.engine.tes3mp_dir", return_value=root):
            self.assertTrue(reset_character_password("Retarded Combine", "morrowind"))
        login = json.loads(path.read_text(encoding="utf-8"))["login"]
        self.assertEqual(len(login["passwordSalt"]), 64)
        expected = hashlib.sha256(("morrowind" + login["passwordSalt"]).encode("utf-8")).hexdigest()
        self.assertEqual(login["passwordHash"], expected)

    def test_reset_never_leaves_the_crashing_state(self):
        root = _make_root()
        _write(root, "Retarded Combine", {"name": "Retarded Combine"})
        with patch("app.engine.tes3mp_dir", return_value=root):
            reset_character_password("Retarded Combine", "morrowind")
            self.assertEqual(accounts_missing_credentials(), [])

    def test_character_progress_survives_the_reset(self):
        root = _make_root()
        path = _write(root, "Retarded Combine", {"name": "Retarded Combine"})
        with patch("app.engine.tes3mp_dir", return_value=root):
            reset_character_password("Retarded Combine", "morrowind")
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(record["inventory"], [1, 2, 3])
        self.assertEqual(len(record["skills"]), 27)

    def test_unknown_player_and_blank_password_are_refused(self):
        root = _make_root()
        with patch("app.engine.tes3mp_dir", return_value=root):
            self.assertFalse(reset_character_password("Nobody", "x"))
            _write(root, "Gorid", {"name": "Gorid"})
            self.assertFalse(reset_character_password("Gorid", ""))


if __name__ == "__main__":
    unittest.main()
