"""TES3MP takes its destination ONLY from tes3mp-client-default.cfg.

A wrong value fails silently: the game opens and connects to nobody, which
reads as a network problem. The stock file ships `destinationAddress =
127.0.0.1`, so any launch path that does not rewrite it sends the player to
their own machine. rettycombine (2026-08-18) lost an evening to this and
finally connected by hand-editing this one field.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import read_client_destination, verify_client_destination

STOCK = "[General]\ndestinationAddress = 127.0.0.1\nport = 25565\npassword = \n"
PARTY = "[General]\ndestinationAddress = 100.110.37.122\nport = 25565\npassword = \n"


def _root(body: str) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "tes3mp-client-default.cfg").write_text(body, encoding="utf-8")
    return root


class ReadDestinationTests(unittest.TestCase):
    def test_reads_host_and_port(self):
        self.assertEqual(
            read_client_destination(_root(PARTY) / "tes3mp-client-default.cfg"),
            ("100.110.37.122", 25565),
        )

    def test_missing_file_is_empty_not_a_crash(self):
        self.assertEqual(
            read_client_destination(Path(tempfile.mkdtemp()) / "nope.cfg"), ("", 0)
        )


class VerifyDestinationTests(unittest.TestCase):
    def test_stock_localhost_is_caught(self):
        msg = verify_client_destination(_root(STOCK), "100.110.37.122", 25565)
        self.assertIn("127.0.0.1", msg)
        self.assertIn("100.110.37.122", msg)

    def test_correct_destination_passes_silently(self):
        self.assertEqual(
            verify_client_destination(_root(PARTY), "100.110.37.122", 25565), ""
        )

    def test_port_mismatch_is_caught(self):
        msg = verify_client_destination(_root(PARTY), "100.110.37.122", 25999)
        self.assertIn("25565", msg)

    def test_host_comparison_is_case_insensitive(self):
        root = _root("[General]\ndestinationAddress = Heller.Example\nport = 25565\n")
        self.assertEqual(verify_client_destination(root, "heller.example", 25565), "")

    def test_absent_config_is_reported_not_ignored(self):
        msg = verify_client_destination(Path(tempfile.mkdtemp()), "100.110.37.122", 25565)
        self.assertIn("no destination", msg)


if __name__ == "__main__":
    unittest.main()
