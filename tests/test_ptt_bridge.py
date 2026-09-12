import json
import os
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from app.ptt_bridge import (
    LocalPttBridge,
    binding_virtual_key,
    keyboard_virtual_key,
    normalize_https_origin,
    voice_origin_from_url,
)


class PttBridgeTests(unittest.TestCase):
    def test_bridge_remembers_the_last_requested_binding(self) -> None:
        bridge = LocalPttBridge({"https://voice.example.test"}, port=0)
        self.assertEqual(bridge.last_virtual_key(), 0x20)
        bridge.remember_binding(ord("V"))
        self.assertEqual(bridge.last_virtual_key(), ord("V"))

    def test_common_keyboard_and_mouse_bindings_map_to_windows_keys(self) -> None:
        self.assertEqual(keyboard_virtual_key("Space"), 0x20)
        self.assertEqual(keyboard_virtual_key("KeyV"), ord("V"))
        self.assertEqual(keyboard_virtual_key("Digit7"), ord("7"))
        self.assertEqual(keyboard_virtual_key("F12"), 0x7B)
        self.assertEqual(binding_virtual_key("mouse", "3"), 0x05)
        self.assertIsNone(binding_virtual_key("mouse", "9"))
        self.assertIsNone(keyboard_virtual_key("MadeUpKey"))

    def test_only_exact_https_origins_are_accepted(self) -> None:
        self.assertEqual(
            normalize_https_origin("https://Voice.Example.test/"),
            "https://voice.example.test",
        )
        self.assertIsNone(normalize_https_origin("http://voice.example.test"))
        self.assertIsNone(normalize_https_origin("https://voice.example.test/path"))
        self.assertEqual(
            voice_origin_from_url("wss://VOICE.example.test/morrowvoice/v1/host"),
            "https://voice.example.test",
        )

    @unittest.skipUnless(os.name == "nt", "Windows loopback companion")
    def test_event_stream_rejects_other_origins_and_streams_boolean_only(self) -> None:
        bridge = LocalPttBridge({"https://voice.example.test"}, port=0)
        with patch.object(bridge, "key_pressed", return_value=True):
            status = bridge.start()
            self.assertTrue(status.running)
            port = bridge._server.server_address[1]  # type: ignore[union-attr]
            try:
                denied = HTTPConnection("127.0.0.1", port, timeout=2)
                denied.request(
                    "GET",
                    "/v1/ptt/events?kind=keyboard&value=Space",
                    headers={"Origin": "https://evil.example"},
                )
                denied_response = denied.getresponse()
                self.assertEqual(denied_response.status, 403)
                denied.close()

                allowed = HTTPConnection("127.0.0.1", port, timeout=2)
                allowed.request(
                    "GET",
                    "/v1/ptt/events?kind=keyboard&value=Space",
                    headers={"Origin": "https://voice.example.test"},
                )
                response = allowed.getresponse()
                self.assertEqual(response.status, 200)
                line = response.readline()
                self.assertEqual(json.loads(line.removeprefix(b"data: ")), {"pressed": True})
                allowed.close()
            finally:
                bridge.stop()


if __name__ == "__main__":
    unittest.main()
