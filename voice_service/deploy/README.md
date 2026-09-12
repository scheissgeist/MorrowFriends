# MorrowFriends voice on one Hetzner server

This bundle runs four isolated services on a Linux VM:

- MorrowFriends relay and friend webpage on `voice.example.com`
- LiveKit signaling on `livekit.example.com`
- LiveKit TURN/TLS on `turn.example.com`
- Redis bound to localhost only

The launcher makes one outbound encrypted connection. Friends never connect to
the host PC and do not need Tailscale for voice. TES3MP can continue using the
existing Tailscale party.

## Before deploying

Use an Ubuntu Hetzner VM with at least 4 vCPUs and 8 GB RAM for comfortable
headroom while a larger party is speaking. Point three DNS A records at its
public IPv4 address:

```text
voice.example.com
livekit.example.com
turn.example.com
```

In the Hetzner Cloud Firewall, allow only:

```text
22/tcp                 your own IP only
80/tcp                 certificate issuance
443/tcp                webpage, signaling, and TURN/TLS
7881/tcp               WebRTC TCP fallback
3478/udp               TURN/UDP
50000-60000/udp        WebRTC media
```

Do not expose ports 6379, 7880, 8080, or 5349 directly.

## Configure on the VM

Install current Docker Engine and the Docker Compose plugin from Docker's
official Ubuntu instructions. Copy this repository to `/opt/morrowfriends`,
then run the renderer from the VM so it can select the correct local TURN
upstream address:

```bash
cd /opt/morrowfriends
python3 voice_service/deploy/configure.py \
  --voice-domain voice.example.com \
  --livekit-domain livekit.example.com \
  --turn-domain turn.example.com \
  --party-id example-party
```

Replace all example domains and choose a private party ID. The command creates
`caddy.yaml`, `livekit.yaml`, and a mode-600 `.env`. It never prints the host
token. Keep `.env` private and do not show it on stream.

Start and verify the stack:

```bash
cd /opt/morrowfriends/voice_service/deploy
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail https://voice.example.com/health
```

## Connect the host launcher

Open **Voice setup** in the future MorrowFriends build and enter:

```text
Relay URL: wss://voice.example.com
Party ID: example-party
Host token: the MORROWVOICE_HOST_TOKEN value from .env
```

The launcher encrypts that token with the host's Windows account. Copy the
friend voice link from the same window. A friend joins TES3MP, types `/voice`
in game, opens the link, enters the one-time code, grants microphone access,
and holds Space to talk.

In v0.4.5 and later, each player can choose any normal keyboard key or mouse
button on the voice page. Keep the MorrowFriends launcher running: its
loopback-only PTT companion lets that binding work while Morrowind has focus.
The friend ZIP must include `MorrowFriends.voice.json` beside the EXE with the
exact approved HTTPS voice origin:

```json
{"allowed_origins":["https://voice.example.com"]}
```

That file contains no credential. The local companion rejects every other web
origin and exposes only whether the chosen PTT key is currently pressed. Current
Chrome versions ask once whether the voice site may access the local network;
friends should choose **Allow** so the page can reach the loopback companion.

## Operations

```bash
docker compose logs --tail=100 relay livekit caddy
docker compose restart relay
docker compose down
```

Restarting the relay invalidates browser position sessions. Players simply type
`/voice` again. `--force` on `configure.py` rotates every credential, so only
use it deliberately and then update the launcher.

This configuration extends LiveKit's official VM pattern: Linux host networking,
Caddy Layer 4 SNI routing, Redis on loopback, TCP/UDP WebRTC paths, TURN/UDP,
and TURN/TLS sharing public port 443.

## Shared Skyhole deployment

Skyhole already runs the shared `hyrule-royale-caddy` container on ports 80/443.
Do not start the default profile there. Render the shared-edge profile instead:

```bash
cd /opt/morrowfriends
python3 voice_service/deploy/configure.py \
  --voice-domain voice.gamebrain.win \
  --livekit-domain livekit.gamebrain.win \
  --turn-domain turn.gamebrain.win \
  --party-id broteam-morrowind \
  --shared-edge

docker compose -p morrowfriends \
  -f voice_service/deploy/docker-compose.skyhole.yml config --quiet
docker compose -p morrowfriends \
  -f voice_service/deploy/docker-compose.skyhole.yml up -d --build
```

This profile joins the relay to the existing `hetzner_default` edge network,
keeps Redis on an internal network, and runs LiveKit on the host network so
WebRTC ICE sees the real public media sockets. Caddy reaches signaling through
the verified `172.19.0.1` edge gateway. Its direct public
media ports are `7881/tcp`, `3478/udp`, `7882/udp`, and the deliberately small
`35000-35020/udp` TURN relay pool; it does not claim 80/443 or LiveKit's default
10,001-port relay range. Install and enable the included systemd timer so a
later shared-Caddy deploy cannot silently remove the voice routes.
