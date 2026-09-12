import unittest

import jwt

from voice_service.server import SlidingWindowLimiter, VoiceRelayConfig, issue_livekit_token


class VoiceServerTests(unittest.TestCase):
    def test_livekit_token_is_short_lived_and_microphone_only(self) -> None:
        config = VoiceRelayConfig(
            party_id="example-party",
            host_token="h" * 32,
            livekit_url="wss://voice.example.test",
            livekit_api_key="devkey",
            livekit_api_secret="s" * 32,
            token_ttl_seconds=600,
        )

        token = issue_livekit_token(config, "Gorid")
        claims = jwt.decode(token, options={"verify_signature": False})

        self.assertEqual(claims["sub"], "Gorid")
        self.assertEqual(claims["name"], "Gorid")
        self.assertEqual(claims["video"]["room"], "morrowfriends-example-party")
        self.assertTrue(claims["video"]["roomJoin"])
        self.assertEqual(claims["video"]["canPublishSources"], ["microphone"])
        self.assertFalse(claims["video"]["canPublishData"])
        self.assertLessEqual(claims["exp"] - claims["nbf"], 600)

    def test_claim_rate_limiter_is_bounded_per_client(self) -> None:
        limiter = SlidingWindowLimiter(attempts=2, window_seconds=60, max_keys=2)
        self.assertTrue(limiter.allow("client-a", now=10))
        self.assertTrue(limiter.allow("client-a", now=11))
        self.assertFalse(limiter.allow("client-a", now=12))
        self.assertTrue(limiter.allow("client-b", now=12))
        self.assertTrue(limiter.allow("client-c", now=13))
        self.assertLessEqual(len(limiter._events), 2)
        self.assertTrue(limiter.allow("client-a", now=71))

    def test_config_rejects_short_host_secret(self) -> None:
        config = VoiceRelayConfig(
            party_id="party",
            host_token="short",
            livekit_url="wss://voice.example.test",
            livekit_api_key="key",
            livekit_api_secret="s" * 32,
        )
        with self.assertRaisesRegex(ValueError, "HOST_TOKEN"):
            config.validate()

    def test_livekit_https_origin_is_available_for_reconnect_validation(self) -> None:
        config = VoiceRelayConfig(
            party_id="party",
            host_token="h" * 32,
            livekit_url="wss://livekit.example.test/rtc",
            livekit_api_key="key",
            livekit_api_secret="s" * 32,
        )

        config.validate()

        self.assertEqual(config.livekit_http_origin, "https://livekit.example.test")

    def test_livekit_url_rejects_csp_injection(self) -> None:
        config = VoiceRelayConfig(
            party_id="party",
            host_token="h" * 32,
            livekit_url="wss://livekit.example.test; https://evil.test",
            livekit_api_key="key",
            livekit_api_secret="s" * 32,
        )

        with self.assertRaisesRegex(ValueError, "LIVEKIT_URL"):
            config.validate()


if __name__ == "__main__":
    unittest.main()
