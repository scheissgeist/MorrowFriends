import asyncio
import json
import socket
import time
import unittest

import httpx
import uvicorn
from websockets.asyncio.client import connect as async_connect
from websockets.sync.client import connect as sync_connect

from app.voice_relay import VoiceRelayBridge, VoiceRelaySettings, _SyncCursor
from voice_service.server import VoiceRelayConfig, create_app


def position_payload() -> dict:
    return {
        "version": 1,
        "sequence": 42,
        "serverUptimeMs": 2000,
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
                "position": {"x": 1000, "y": 0, "z": 0},
                "rotation": {"x": 0, "z": 0},
            },
        ],
        "_fileMtime": time.time(),
    }


class VoiceEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.listener = listener
        self.port = listener.getsockname()[1]
        config = VoiceRelayConfig(
            party_id="e2e-party",
            host_token="h" * 32,
            livekit_url="ws://127.0.0.1:7880",
            livekit_api_key="devkey",
            livekit_api_secret="s" * 32,
        )
        server_config = uvicorn.Config(
            create_app(config),
            log_level="critical",
            lifespan="off",
            ws="websockets-sansio",
        )
        self.server = uvicorn.Server(server_config)
        self.server_task = asyncio.create_task(self.server.serve(sockets=[listener]))
        for _ in range(100):
            if self.server.started:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(self.server.started)

    async def asyncTearDown(self) -> None:
        self.server.should_exit = True
        await asyncio.wait_for(self.server_task, timeout=5)
        self.listener.close()

    async def test_host_claim_and_player_mix_use_the_real_wire_protocol(self) -> None:
        settings = VoiceRelaySettings(
            f"ws://127.0.0.1:{self.port}", "e2e-party", "h" * 32
        )
        claims = {
            "version": 1,
            "claims": {
                "A1B2C3D4E5F6G7H8": {
                    "player": "Gorid",
                    "issuedAtMs": 1000,
                    "expiresAtMs": 5000,
                }
            },
        }
        bridge = VoiceRelayBridge(
            settings,
            snapshot_source=position_payload,
            claims_source=lambda: claims,
        )

        def upload_host_state() -> None:
            with sync_connect(
                settings.host_endpoint,
                additional_headers={"Authorization": "Bearer " + settings.host_token},
                proxy=None,
            ) as connection:
                self.assertTrue(bridge._sync_once(connection, _SyncCursor()))

        await asyncio.to_thread(upload_host_state)

        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{self.port}", trust_env=False
        ) as client:
            response = await client.post(
                "/v1/claim",
                json={"party_id": "e2e-party", "code": "A1B2C3D4E5F6G7H8"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            credentials = response.json()
            replay = await client.post(
                "/v1/claim",
                json={"party_id": "e2e-party", "code": "A1B2C3D4E5F6G7H8"},
            )
            self.assertEqual(replay.status_code, 400)

        async with async_connect(
            f"ws://127.0.0.1:{self.port}/v1/player", proxy=None
        ) as player:
            await player.send(
                json.dumps({"type": "auth", "token": credentials["position_token"]})
            )
            frame = json.loads(await asyncio.wait_for(player.recv(), timeout=2))

        self.assertEqual(frame["listener"], "Gorid")
        self.assertFalse(frame["stale"])
        sluxslol = next(item for item in frame["speakers"] if item["player"] == "Sluxslol")
        self.assertAlmostEqual(sluxslol["gain"], 0.8)
        self.assertEqual(frame["environment"], "interior")
        self.assertEqual(
            sluxslol["position"],
            {"right": 1000.0, "up": 0.0, "forward": 0.0},
        )


if __name__ == "__main__":
    unittest.main()
