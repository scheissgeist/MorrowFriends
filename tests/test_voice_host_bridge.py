import json
import unittest

from app.voice_relay import VoiceRelayBridge, VoiceRelaySettings, _SyncCursor


class FakeConnection:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def recv(self, timeout: float | None = None) -> str:
        _ = timeout
        kind = self.sent[-1]["type"]
        return json.dumps({"type": "ack", "kind": kind, "generation": len(self.sent)})

    def close(self) -> None:
        return


def position_payload(*, sequence: int = 7, mtime: float = 98.5) -> dict:
    return {
        "version": 1,
        "sequence": sequence,
        "serverUptimeMs": 2000,
        "players": [],
        "_fileMtime": mtime,
    }


class VoiceHostBridgeTests(unittest.TestCase):
    def settings(self, url: str = "wss://voice.example.test") -> VoiceRelaySettings:
        return VoiceRelaySettings(url, "example-party", "h" * 32)

    def test_external_relay_requires_tls(self) -> None:
        with self.assertRaisesRegex(ValueError, "encrypted"):
            VoiceRelaySettings(
                "ws://voice.example.test", "party", "h" * 32
            ).validate()
        self.settings("ws://127.0.0.1:8080").validate()

    def test_host_endpoint_preserves_reverse_proxy_prefix(self) -> None:
        settings = self.settings("wss://voice.example.test/morrowvoice/")
        self.assertEqual(
            settings.host_endpoint,
            "wss://voice.example.test/morrowvoice/v1/host",
        )
        self.assertEqual(
            settings.friend_url,
            "https://voice.example.test/morrowvoice/?party=example-party",
        )

    def test_sync_coalesces_positions_and_reliably_sends_empty_claim_state(self) -> None:
        snapshot = position_payload()
        bridge = VoiceRelayBridge(
            self.settings(),
            snapshot_source=lambda: dict(snapshot),
            claims_source=lambda: {},
            wall_clock=lambda: 100.0,
        )
        connection = FakeConnection()
        cursor = _SyncCursor()

        self.assertTrue(bridge._sync_once(connection, cursor))
        self.assertFalse(bridge._sync_once(connection, cursor))

        self.assertEqual([item["type"] for item in connection.sent], ["snapshot", "claims"])
        self.assertEqual(connection.sent[0]["observedAgeMs"], 1500)
        self.assertNotIn("_fileMtime", connection.sent[0])
        self.assertEqual(connection.sent[1]["claims"], {})
        self.assertNotIn("h" * 32, json.dumps(connection.sent))

    def test_new_position_sequence_replaces_latest_state_without_queueing(self) -> None:
        snapshot = position_payload()
        bridge = VoiceRelayBridge(
            self.settings(),
            snapshot_source=lambda: dict(snapshot),
            claims_source=lambda: {},
            wall_clock=lambda: 100.0,
        )
        connection = FakeConnection()
        cursor = _SyncCursor()
        bridge._sync_once(connection, cursor)

        snapshot["sequence"] = 8
        bridge._sync_once(connection, cursor)

        positions = [item for item in connection.sent if item["type"] == "snapshot"]
        self.assertEqual([item["sequence"] for item in positions], [7, 8])

    def test_bad_ack_does_not_advance_cursor(self) -> None:
        class BadConnection(FakeConnection):
            def recv(self, timeout: float | None = None) -> str:
                return json.dumps({"type": "error", "error": "wrong party"})

        bridge = VoiceRelayBridge(
            self.settings(),
            snapshot_source=lambda: position_payload(),
            claims_source=lambda: {},
            wall_clock=lambda: 100.0,
        )
        cursor = _SyncCursor()
        with self.assertRaisesRegex(RuntimeError, "wrong party"):
            bridge._sync_once(BadConnection(), cursor)
        self.assertIsNone(cursor.snapshot)

    def test_transient_claim_read_does_not_publish_a_false_clear(self) -> None:
        bridge = VoiceRelayBridge(
            self.settings(),
            snapshot_source=lambda: {},
            claims_source=lambda: {"_readError": True},
        )
        connection = FakeConnection()

        self.assertFalse(bridge._sync_once(connection, _SyncCursor()))
        self.assertEqual(connection.sent, [])


if __name__ == "__main__":
    unittest.main()
