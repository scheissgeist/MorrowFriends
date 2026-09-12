#!/usr/bin/env python3
"""MorrowFriends server admin panel.

Modelled on /opt/dods-panel/app.py, already running on the same host: Flask,
HTTP Basic auth from env, JSON routes, served behind Caddy.

Exists because the desktop launcher cannot run a public server — the TES3MP
process is a CHILD of the launcher (killing MorrowFriends took the server down
with it on 2026-08-18), the launcher is the only voice uplink, and it crashed
five times that evening. Rules and moderation have to live somewhere that stays
up.

Routes:
  GET  /                    dashboard
  GET  /api/status          live players + rule values + broken-account warnings
  POST /api/rule            {key, value}   toggle one co-op rule
  POST /api/player/rank     {name, rank, console}
  POST /api/player/password {name, password}
  POST /api/player/kick     {name}
  POST /api/player/expulsion {name}   lift one player's guild expulsions
  POST /api/expulsion/clear-all       lift everyone's
  POST /api/broadcast       {message}
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from coop_rules import RULES, read_rules, set_rule
from players import (
    OWNER_RANK,
    broken_accounts,
    clear_expulsions,
    list_players,
    live_players,
    queue_command,
    reset_password,
    set_staff_rank,
)

TES3MP_ROOT = Path(os.environ.get("TES3MP_ROOT", "/opt/morrowfriends/tes3mp"))
DATA_ROOT = TES3MP_ROOT / "server" / "data"
CONFIG_LUA = TES3MP_ROOT / "server" / "scripts" / "config.lua"

PANEL_USER = os.environ.get("PANEL_USER", "admin")
PANEL_PASS = os.environ.get("PANEL_PASS", "")

app = Flask(__name__)


def check_auth(user: str, password: str) -> bool:
    # An unset password must never mean "anyone gets in". dods-panel ships
    # PANEL_PASS=changeme as a default; here an empty value locks the panel.
    if not PANEL_PASS:
        return False
    return user == PANEL_USER and password == PANEL_PASS


def requires_auth(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username or "", auth.password or ""):
            return Response(
                "Auth required", 401,
                {"WWW-Authenticate": 'Basic realm="MorrowFriends Panel"'},
            )
        return view(*args, **kwargs)

    return wrapped


@app.get("/")
@requires_auth
def dashboard():
    return render_template(
        "dashboard.html",
        rules=RULES,
        values=read_rules(CONFIG_LUA),
        players=list_players(DATA_ROOT),
        online=live_players(DATA_ROOT),
        broken=broken_accounts(DATA_ROOT),
        owner_rank=OWNER_RANK,
    )


@app.get("/api/status")
@requires_auth
def status():
    return jsonify(
        {
            "rules": read_rules(CONFIG_LUA),
            "online": live_players(DATA_ROOT),
            "players": [vars(row) for row in list_players(DATA_ROOT)],
            "broken": broken_accounts(DATA_ROOT),
        }
    )


@app.post("/api/rule")
@requires_auth
def api_rule():
    body = request.get_json(silent=True) or {}
    key = str(body.get("key", ""))
    value = bool(body.get("value"))
    try:
        ok = set_rule(CONFIG_LUA, key, value)
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    # set_rule reads the file back; report the confirmed value, not the request.
    return jsonify({"ok": ok, "key": key, "value": read_rules(CONFIG_LUA).get(key)})


@app.post("/api/player/rank")
@requires_auth
def api_rank():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    rank = int(body.get("rank", 0))
    console = bool(body.get("console"))
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    return jsonify({"ok": set_staff_rank(DATA_ROOT, name, rank, console)})


@app.post("/api/player/password")
@requires_auth
def api_password():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    password = str(body.get("password", ""))
    if not name or not password:
        return jsonify({"ok": False, "error": "name and password are required"}), 400
    try:
        return jsonify({"ok": reset_password(DATA_ROOT, name, password)})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/player/kick")
@requires_auth
def api_kick():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    queue_command(DATA_ROOT, {"action": "kick", "target": name})
    return jsonify({"ok": True, "queued": "kick"})


@app.post("/api/player/ban")
@requires_auth
def api_ban():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    queue_command(DATA_ROOT, {"action": "ban", "target": name})
    return jsonify({"ok": True, "queued": "ban"})


def _online_names() -> set[str]:
    """Lowercased account names of everyone connected right now."""
    names: set[str] = set()
    for entry in live_players(DATA_ROOT):
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name:
                names.add(name.lower())
    return names


@app.post("/api/player/expulsion")
@requires_auth
def api_expulsion():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400

    if name.lower() in _online_names():
        # A connected player's faction state is held in memory and would
        # overwrite any edit to the saved record, so hand it to the roster Lua
        # to apply against the live player object instead.
        queue_command(DATA_ROOT, {"action": "clear_expulsion", "target": name})
        return jsonify({"ok": True, "name": name, "route": "queued"})

    return jsonify(
        {"ok": clear_expulsions(DATA_ROOT, name), "name": name, "route": "file"}
    )


@app.post("/api/expulsion/clear-all")
@requires_auth
def api_expulsion_clear_all():
    online = _online_names()
    cleared: list[str] = []
    failed: list[str] = []

    for row in list_players(DATA_ROOT):
        if not row.expelled_from or row.name.lower() in online:
            continue
        (cleared if clear_expulsions(DATA_ROOT, row.name) else failed).append(row.name)

    # ONE sweep command for every connected player. host_commands.json holds a
    # single command, so queuing one per player would have each overwrite the
    # last and silently drop all but the final name.
    queue_command(DATA_ROOT, {"action": "clear_expulsion"})

    return jsonify({"ok": not failed, "cleared": cleared, "failed": failed})


@app.post("/api/broadcast")
@requires_auth
def api_broadcast():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()
    if not message:
        return jsonify({"ok": False, "error": "message is required"}), 400
    queue_command(DATA_ROOT, {"action": "broadcast", "message": message})
    return jsonify({"ok": True, "queued": "broadcast"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PANEL_PORT", "8091")))
