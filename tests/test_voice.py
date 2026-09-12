import math
import unittest

from app.voice import (
    PlayerPose,
    PositionSnapshot,
    acoustic_environment,
    distance_between,
    listener_space_position,
    parse_position_snapshot,
    proximity_gain,
    proximity_mix,
)


def pose(
    name: str,
    *,
    cell: str = "Balmora",
    exterior: bool = False,
    x: float = 0,
    y: float = 0,
    z: float = 0,
    rot_z: float = 0,
) -> PlayerPose:
    return PlayerPose(name, cell, exterior, x, y, z, 0, rot_z)


class VoicePositionTests(unittest.TestCase):
    def test_parses_valid_pose_and_drops_nonfinite_row(self) -> None:
        payload = {
            "version": 1,
            "sequence": 42,
            "serverUptimeMs": 9001,
            "players": [
                {
                    "name": "Gorid",
                    "cell": "Balmora",
                    "exterior": False,
                    "position": {"x": 10, "y": 20, "z": 30},
                    "rotation": {"x": 0.5, "z": 1.25},
                },
                {
                    "name": "Broken",
                    "cell": "Balmora",
                    "position": {"x": math.nan, "y": 0, "z": 0},
                    "rotation": {"x": 0, "z": 0},
                },
            ],
        }

        snapshot = parse_position_snapshot(payload, observed_at=12.5)

        self.assertEqual(snapshot.sequence, 42)
        self.assertEqual(snapshot.server_uptime_ms, 9001)
        self.assertEqual([player.name for player in snapshot.players], ["Gorid"])
        self.assertFalse(snapshot.is_stale(now=14.0, timeout=2.0))
        self.assertTrue(snapshot.is_stale(now=14.6, timeout=2.0))

    def test_separate_interiors_and_interior_exterior_are_silent(self) -> None:
        listener = pose("Listener", cell="Balmora, Guild of Mages")
        other_interior = pose("Speaker", cell="Balmora, Eight Plates")
        outside = pose("Outside", cell="-3, -2", exterior=True)

        self.assertIsNone(distance_between(listener, other_interior))
        self.assertEqual(proximity_gain(listener, other_interior), 0)
        self.assertEqual(proximity_gain(listener, outside), 0)

    def test_exterior_players_can_hear_across_cell_boundaries(self) -> None:
        listener = pose("Listener", cell="-3, -2", exterior=True, x=0)
        speaker = pose("Speaker", cell="-2, -2", exterior=True, x=1000)

        self.assertEqual(distance_between(listener, speaker), 1000)
        self.assertAlmostEqual(proximity_gain(listener, speaker), 0.8)

    def test_gain_is_full_nearby_and_zero_at_outer_radius(self) -> None:
        listener = pose("Listener")
        self.assertEqual(proximity_gain(listener, pose("Near", x=500)), 1)
        self.assertEqual(proximity_gain(listener, pose("Far", x=3000)), 0)

    def test_listener_space_tracks_facing_direction_and_height(self) -> None:
        listener = pose("Listener", rot_z=math.pi / 2)

        right, up, forward = listener_space_position(
            listener, pose("Speaker", x=100, y=25, z=40)
        )

        self.assertAlmostEqual(right, -25)
        self.assertAlmostEqual(up, 40)
        self.assertAlmostEqual(forward, 100)

    def test_listener_space_is_blocked_across_separate_interiors(self) -> None:
        listener = pose("Listener", cell="Balmora, Guild of Mages")
        speaker = pose("Speaker", cell="Balmora, Eight Plates")

        self.assertIsNone(listener_space_position(listener, speaker))

    def test_acoustic_environment_uses_exterior_and_cell_kind(self) -> None:
        self.assertEqual(
            acoustic_environment(pose("Outside", exterior=True, cell="-3, -2")),
            "outdoors",
        )
        self.assertEqual(
            acoustic_environment(pose("Cave", cell="Addamasartus")),
            "interior",
        )
        self.assertEqual(
            acoustic_environment(pose("Mine", cell="Shulk Egg Mine")),
            "cavern",
        )
        self.assertEqual(
            acoustic_environment(pose("Temple", cell="Balmora, Temple")),
            "large-interior",
        )

    def test_stale_snapshot_mutes_every_speaker(self) -> None:
        snapshot = PositionSnapshot(
            version=1,
            sequence=5,
            server_uptime_ms=1000,
            observed_at=10.0,
            players=(pose("Listener"), pose("Near", x=100), pose("Far", x=1000)),
        )

        self.assertEqual(
            proximity_mix(snapshot, "Listener", now=12.1, stale_timeout=2.0),
            {"Near": 0.0, "Far": 0.0},
        )


if __name__ == "__main__":
    unittest.main()
