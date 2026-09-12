import argparse
import tempfile
import unittest
from pathlib import Path

import yaml

from voice_service.deploy.configure import configure, valid_domain


class VoiceDeployTests(unittest.TestCase):
    def arguments(self, output: Path) -> argparse.Namespace:
        return argparse.Namespace(
            voice_domain="voice.example.test",
            livekit_domain="livekit.example.test",
            turn_domain="turn.example.test",
            party_id="example-party",
            turn_upstream_ip="10.0.0.4",
            shared_edge=False,
            output=output,
            force=False,
        )

    def test_renderer_separates_public_config_from_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            rendered = configure(self.arguments(output))
            environment = (output / ".env").read_text(encoding="utf-8")
            caddy = (output / "caddy.yaml").read_text(encoding="utf-8")
            livekit = (output / "livekit.yaml").read_text(encoding="utf-8")

            self.assertIn("MORROWVOICE_HOST_TOKEN=", environment)
            self.assertIn("LIVEKIT_API_SECRET=", environment)
            self.assertNotIn("MORROWVOICE_HOST_TOKEN", caddy + livekit)
            self.assertNotIn("LIVEKIT_API_SECRET", caddy + livekit)
            self.assertEqual(
                rendered["friend_url"],
                "https://voice.example.test/?party=example-party",
            )
            self.assertEqual(yaml.safe_load(livekit)["turn"]["domain"], "turn.example.test")
            self.assertIn("10.0.0.4:5349", caddy)

    def test_renderer_refuses_implicit_secret_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = self.arguments(output)
            configure(args)
            with self.assertRaises(FileExistsError):
                configure(args)

    def test_shared_edge_profile_uses_udp_mux_and_existing_caddy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            args = self.arguments(output)
            args.shared_edge = True
            configure(args)

            self.assertFalse((output / "caddy.yaml").exists())
            caddy = (output / "caddy.morrowfriends").read_text(encoding="utf-8")
            livekit = yaml.safe_load((output / "livekit.yaml").read_text(encoding="utf-8"))
            self.assertIn("morrowfriends-voice-relay:8080", caddy)
            self.assertIn("172.19.0.1:7880", caddy)
            self.assertEqual(livekit["rtc"]["udp_port"], 7882)
            self.assertNotIn("port_range_start", livekit["rtc"])
            self.assertNotIn("redis", livekit)
            self.assertNotIn("tls_port", livekit["turn"])
            self.assertEqual(livekit["turn"]["relay_range_start"], 35000)
            self.assertEqual(livekit["turn"]["relay_range_end"], 35020)

            # The live host's compose profile is intentionally excluded from
            # public source exports. Validate it when present in the private
            # operations tree without making public CI depend on that file.
            compose_path = (
                Path(__file__).resolve().parents[1]
                / "voice_service"
                / "deploy"
                / "docker-compose.skyhole.yml"
            )
            if compose_path.is_file():
                compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
                livekit_service = compose["services"]["livekit"]
                self.assertEqual(livekit_service["network_mode"], "host")
                self.assertNotIn("ports", livekit_service)
                self.assertNotIn("networks", livekit_service)

    def test_domain_validation_rejects_urls_and_single_labels(self) -> None:
        for value in ("https://voice.example.test", "localhost", "bad_domain.test"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                valid_domain(value)


if __name__ == "__main__":
    unittest.main()
