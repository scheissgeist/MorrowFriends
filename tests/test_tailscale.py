from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from app.tailscale import is_tailscale_ip, probe_tailscale


class TailscaleCapabilityTests(unittest.TestCase):
    def test_ip_classification(self) -> None:
        self.assertTrue(is_tailscale_ip("100.110.37.122"))
        self.assertFalse(is_tailscale_ip("192.168.1.2"))
        self.assertFalse(is_tailscale_ip("not-an-ip"))

    @patch("app.tailscale._tailscale_executable", return_value=None)
    def test_missing_client_blocks_tailscale_host(self, _executable) -> None:
        capability = probe_tailscale("100.110.37.122")
        self.assertTrue(capability.required)
        self.assertFalse(capability.installed)
        self.assertFalse(capability.ready)

    @patch("app.tailscale._tailscale_executable", return_value="tailscale")
    @patch("app.tailscale.subprocess.run")
    def test_visible_shared_host_is_ready(self, run, _executable) -> None:
        payload = {
            "BackendState": "Running",
            "Self": {"TailscaleIPs": ["100.70.1.2"]},
            "Peer": {
                "node": {
                    "HostName": "heller",
                    "Online": True,
                    "TailscaleIPs": ["100.110.37.122"],
                }
            },
        }
        run.return_value = subprocess.CompletedProcess(
            ["tailscale", "status", "--json"], 0, json.dumps(payload), ""
        )
        capability = probe_tailscale("100.110.37.122")
        self.assertTrue(capability.ready)
        self.assertEqual(capability.peer_name, "heller")


if __name__ == "__main__":
    unittest.main()


class NullTailscaleIPsTests(unittest.TestCase):
    """Tailscale emits `"TailscaleIPs": null` for a node with no assigned
    addresses. `.get(key, [])` returns None for a present-but-null key, so the
    comprehensions raised "'NoneType' object is not iterable" and killed Play
    for a friend whose machine had just joined the tailnet (2026-08-18).
    """

    def _probe_with(self, payload):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )
        with patch("app.tailscale._tailscale_executable", return_value="ts.exe"), \
             patch("app.tailscale.subprocess.run", return_value=completed):
            return probe_tailscale("100.110.37.122")

    def test_null_self_ips_does_not_raise(self):
        cap = self._probe_with(
            {"BackendState": "Running", "Self": {"TailscaleIPs": None}, "Peer": {}}
        )
        self.assertEqual(cap.self_ip, "")

    def test_null_peer_ips_does_not_raise(self):
        cap = self._probe_with(
            {
                "BackendState": "Running",
                "Self": {"TailscaleIPs": ["100.1.1.1"]},
                "Peer": {"n": {"HostName": "h", "TailscaleIPs": None}},
            }
        )
        self.assertFalse(cap.peer_visible)

    def test_host_still_found_when_a_sibling_peer_is_null(self):
        cap = self._probe_with(
            {
                "BackendState": "Running",
                "Self": {"TailscaleIPs": ["100.1.1.1"]},
                "Peer": {
                    "a": {"HostName": "broken", "TailscaleIPs": None},
                    "b": {"HostName": "Heller", "TailscaleIPs": ["100.110.37.122"], "Online": True},
                },
            }
        )
        self.assertTrue(cap.peer_visible)
        self.assertEqual(cap.peer_name, "Heller")
