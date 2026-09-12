import unittest

from voice_service.core import PartyState, RelayError


def snapshot(*, uptime: int = 1000, x: float = 0) -> dict:
    return {
        "version": 1,
        "sequence": 1,
        "serverUptimeMs": uptime,
        "players": [
            {
                "name": "Gorid",
                "cell": "Balmora",
                "exterior": False,
                "position": {"x": 0, "y": 0, "z": 0},
                "rotation": {"x": 0, "z": 0},
            },
            {
                "name": "Sluxslol",
                "cell": "Balmora",
                "exterior": False,
                "position": {"x": x, "y": 0, "z": 0},
                "rotation": {"x": 0, "z": 0},
            },
        ],
    }


class VoiceRelayTests(unittest.TestCase):
    def test_claim_is_bound_to_connected_player_and_single_use(self) -> None:
        state = PartyState()
        state.update_snapshot(snapshot(x=100), now=10.0)
        state.update_claims(
            {
                "claims": {
                    "A1B2C3D4E5F6G7H8": {
                        "player": "Gorid",
                        "issuedAtMs": 500,
                        "expiresAtMs": 5000,
                    }
                }
            }
        )

        session = state.redeem("a1b2c3d4e5f6g7h8", now=10.5)

        self.assertEqual(session.player, "Gorid")
        with self.assertRaises(RelayError):
            state.redeem("A1B2C3D4E5F6G7H8", now=10.6)

        # The host publishes the complete claim file repeatedly. A used code
        # must stay consumed even if it appears in a later full snapshot.
        state.update_claims(
            {
                "claims": {
                    "A1B2C3D4E5F6G7H8": {
                        "player": "Gorid",
                        "issuedAtMs": 500,
                        "expiresAtMs": 5000,
                    }
                }
            }
        )
        with self.assertRaises(RelayError):
            state.redeem("A1B2C3D4E5F6G7H8", now=10.7)

    def test_expired_and_disconnected_claims_fail_closed(self) -> None:
        state = PartyState()
        state.update_snapshot(snapshot(uptime=6000), now=10.0)
        state.update_claims(
            {
                "claims": {
                    "A1B2C3D4E5F6G7H8": {
                        "player": "Gorid",
                        "issuedAtMs": 500,
                        "expiresAtMs": 5000,
                    },
                    "Z1Y2X3W4V5U6T7S8": {
                        "player": "NotConnected",
                        "issuedAtMs": 500,
                        "expiresAtMs": 9000,
                    },
                }
            }
        )

        with self.assertRaisesRegex(RelayError, "expired"):
            state.redeem("A1B2C3D4E5F6G7H8", now=10.1)
        with self.assertRaisesRegex(RelayError, "not connected"):
            state.redeem("Z1Y2X3W4V5U6T7S8", now=10.1)

    def test_auto_claim_redeems_the_connected_players_pending_code(self) -> None:
        state = PartyState()
        state.update_snapshot(snapshot(x=100), now=10.0)
        state.update_claims(
            {
                "claims": {
                    "A1B2C3D4E5F6G7H8": {
                        "player": "Gorid",
                        "issuedAtMs": 500,
                        "expiresAtMs": 5000,
                    }
                }
            }
        )
        session = state.redeem_for_player("gorid", now=10.5)
        self.assertEqual(session.player, "Gorid")
        with self.assertRaises(RelayError):
            state.redeem_for_player("Gorid", now=10.6)

    def test_mix_tracks_distance_and_mutes_when_snapshot_stales(self) -> None:
        state = PartyState(stale_timeout=2.0)
        state.update_snapshot(snapshot(x=1000), now=10.0)
        state.update_claims(
            {
                "claims": {
                    "A1B2C3D4E5F6G7H8": {
                        "player": "Gorid",
                        "issuedAtMs": 500,
                        "expiresAtMs": 5000,
                    }
                }
            }
        )
        session = state.redeem("A1B2C3D4E5F6G7H8", now=10.1)

        live = state.player_frame(session.token, now=10.2)
        stale = state.player_frame(session.token, now=12.1)

        self.assertAlmostEqual(live["speakers"][0]["gain"], 0.8)
        self.assertEqual(live["environment"], "interior")
        self.assertEqual(
            live["speakers"][0]["position"],
            {"right": 1000.0, "up": 0.0, "forward": 0.0},
        )
        self.assertFalse(live["stale"])
        self.assertEqual(stale["speakers"][0]["gain"], 0)
        self.assertTrue(stale["stale"])

    def test_oversized_snapshot_is_rejected(self) -> None:
        state = PartyState()
        payload = snapshot()
        payload["players"] = payload["players"] * 33
        with self.assertRaisesRegex(RelayError, "oversized"):
            state.update_snapshot(payload)

    def test_snapshot_observation_age_is_preserved_across_relay_reconnect(self) -> None:
        state = PartyState(stale_timeout=2.0)
        payload = snapshot()
        payload["observedAgeMs"] = 2500

        state.update_snapshot(payload, now=10.0)

        self.assertTrue(state.snapshot.is_stale(now=10.0, timeout=2.0))

    def test_server_restart_invalidates_old_browser_sessions(self) -> None:
        state = PartyState()
        state.update_snapshot(snapshot(uptime=6000), now=10.0)
        state.update_claims(
            {
                "claims": {
                    "A1B2C3D4E5F6G7H8": {
                        "player": "Gorid",
                        "issuedAtMs": 500,
                        "expiresAtMs": 9000,
                    }
                }
            }
        )
        session = state.redeem("A1B2C3D4E5F6G7H8", now=10.1)

        state.update_snapshot(snapshot(uptime=10), now=10.2)

        with self.assertRaisesRegex(RelayError, "invalid or expired"):
            state.session(session.token, now=10.3)


if __name__ == "__main__":
    unittest.main()
