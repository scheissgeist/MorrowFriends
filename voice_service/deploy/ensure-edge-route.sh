#!/usr/bin/env sh
# Restore MorrowFriends' blocks if another Skyhole deploy rewrites the shared
# Caddyfile. Append in place so the running container's read-only bind mount
# keeps the same inode.
set -eu

caddyfile="${SHARED_CADDYFILE:-/opt/hyrule-royale/deploy/hetzner/Caddyfile}"
route_file="${MORROWFRIENDS_ROUTE_FILE:-/opt/morrowfriends/voice_service/deploy/caddy.morrowfriends}"
container="${CADDY_CONTAINER:-hyrule-royale-caddy}"
marker="voice.gamebrain.win"

if [ ! -f "$caddyfile" ]; then
  echo "shared Caddyfile not found at $caddyfile" >&2
  exit 1
fi
if [ ! -f "$route_file" ]; then
  echo "MorrowFriends route file not found at $route_file" >&2
  exit 1
fi
if grep -q "$marker" "$caddyfile"; then
  echo "MorrowFriends edge routes present"
  exit 0
fi

echo "MorrowFriends edge routes missing -- restoring" >&2
cp -a "$caddyfile" "$caddyfile.bak.morrowfriends.$(date -u +%Y%m%dT%H%M%SZ)"
printf '\n' >> "$caddyfile"
cat "$route_file" >> "$caddyfile"

if ! docker run --rm -v "$caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine \
    caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1; then
  echo "restored shared Caddyfile failed validation; Caddy was not reloaded" >&2
  exit 1
fi

docker exec "$container" caddy reload \
  --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
echo "MorrowFriends edge routes restored"
