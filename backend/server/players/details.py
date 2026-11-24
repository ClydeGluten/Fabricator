"""Read player NBT and issue a small allowlist of validated in-game actions.

Player files are strictly read-only. Live reads use vanilla's `data get entity`
through the existing process console, with an explicitly labelled save-file
fallback. No companion mod or exposed RCON listener is needed.
"""
from __future__ import annotations

import gzip
import io
import math
import re
import struct
import uuid

import nbtlib

from backend.server.manager import ServerManager
from backend.server.players import files, lastseen, live, service
from backend.utils.time import iso_z_now, iso_z_from_timestamp

MAX_NBT_BYTES = 8 * 1024 * 1024
NAME_RE = re.compile(r"[A-Za-z0-9_]{1,16}")
DIMENSION_RE = re.compile(r"[a-z0-9_.-]+:[a-z0-9_./-]+")
GAME_MODES = ("survival", "creative", "adventure", "spectator")


def valid_name(value):
    if not isinstance(value, str) or not NAME_RE.fullmatch(value):
        raise ValueError("Use a Java player name (1–16 letters, digits or underscores).")
    return value


def _get(data, *keys, default=None):
    for key in keys:
        if key in data:
            return data[key]
    return default


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _item(raw, slot=None):
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    count = _number(_get(raw, "count", "Count", default=1))
    if count is None or count <= 0:
        return None
    return {
        "slot": slot if slot is not None else int(_get(raw, "slot", "Slot", default=0)),
        "id": str(raw["id"]),
        "count": int(count),
        # SNBT preserves enchantments, custom names, modded components and item
        # data without guessing a particular component schema or rendering HTML.
        "data": raw.snbt()[:16384] if hasattr(raw, "snbt") else str(raw)[:16384],
    }


def _items(raw):
    if not isinstance(raw, (list, nbtlib.List)):
        return []
    return [item for entry in raw[:256] if (item := _item(entry)) is not None]


def normalize(data):
    """Project only the player-card fields, supporting old and new NBT names."""
    position = _get(data, "Pos", "pos", default=[])
    coordinates = None
    if isinstance(position, (list, nbtlib.List)) and len(position) == 3:
        values = [_number(v) for v in position]
        if all(v is not None for v in values):
            coordinates = dict(zip(("x", "y", "z"), values))
    mode = _get(data, "playerGameType", "game_mode", "player_game_type")
    if isinstance(mode, str):
        game_mode = str(mode)
    else:
        game_mode = GAME_MODES[int(mode)] if _number(mode) in range(4) else None
    inventory = _items(_get(data, "Inventory", "inventory", default=[]))
    equipment = []
    equipment_data = data.get("equipment", {})
    if isinstance(equipment_data, dict):
        for slot, entry in equipment_data.items():
            item = _item(entry, str(slot))
            if item:
                equipment.append(item)
    # Classic saves keep worn armour and offhand in Inventory too.
    for item in inventory:
        if item["slot"] in (100, 101, 102, 103, -106, 150):
            labels = {100: "feet", 101: "legs", 102: "chest", 103: "head", -106: "offhand", 150: "offhand"}
            equipment.append({**item, "slot": labels[item["slot"]]})
    food = data.get("food", {})
    if not isinstance(food, dict):
        food = {}
    dimension = _get(data, "Dimension", "dimension")
    if isinstance(dimension, (int, nbtlib.Int)):
        dimension = {-1: "minecraft:the_nether", 0: "minecraft:overworld", 1: "minecraft:the_end"}.get(int(dimension), str(dimension))
    return {
        "position": coordinates,
        "dimension": str(dimension) if dimension is not None else None,
        "health": _number(_get(data, "Health", "health")),
        "food": _number(_get(data, "foodLevel", "food_level", default=food.get("food_level"))),
        "saturation": _number(_get(data, "foodSaturationLevel", "food_saturation_level", default=food.get("saturation_level"))),
        "experienceLevel": _number(_get(data, "XpLevel", "xp_level")),
        "gameMode": game_mode,
        "inventory": [item for item in inventory if 0 <= item["slot"] <= 35],
        "equipment": equipment,
        "enderChest": _items(_get(data, "EnderItems", "ender_items", "ender_chest", default=[])),
    }


def _known_uuid(install, server, name, online_player):
    if online_player and online_player.get("uuid"):
        return str(uuid.UUID(online_player["uuid"]))
    for filename in (service.USERCACHE_FILE, service.WHITELIST_FILE, service.OPS_FILE):
        entry = files.find_entry_by_name(files.read_json_list(install, filename), name)
        if entry and entry.get("uuid"):
            try:
                return str(uuid.UUID(entry["uuid"]))
            except (ValueError, TypeError, AttributeError):
                continue
    if not server.get("onlineMode", True):
        return str(files.offline_uuid(name))
    return None


def _saved_data(install, server, uid):
    if not uid:
        return None
    world = files._resolve_within(install, lastseen.read_level_name(install, server))
    candidates = []
    for layout in ("players/data", "playerdata"):
        for suffix in (".dat", ".dat_old"):
            path = files._resolve_within(install, str(world.relative_to(install.resolve()) / layout / (uid + suffix)))
            if path.is_file():
                candidates.append(path)
    if not candidates:
        return None
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            # Bounded decompression, never nbtlib.load directly on arbitrary
            # uploaded gzip data. The output timestamp is the save, not now.
            with gzip.open(path, "rb") as stream:
                raw = stream.read(MAX_NBT_BYTES + 1)
            if len(raw) > MAX_NBT_BYTES:
                continue
            parsed = nbtlib.File.parse(io.BytesIO(raw))
            return normalize(parsed), iso_z_from_timestamp(path.stat().st_mtime)
        except (OSError, EOFError, ValueError, TypeError, KeyError, IndexError, RecursionError, struct.error):
            continue
    raise ValueError("The saved player data is unreadable or too large.")


def get_details(registry, server, name):
    valid_name(name)
    install = registry.resolve_install_path(server).resolve()
    online = live.list_online(registry, server)
    player = next((p for p in online if p["name"].lower() == name.lower()), None)
    if player:
        name = valid_name(player["name"])
    uid = _known_uuid(install, server, name, player)
    result = {"name": name, "uuid": uid, "online": bool(player), "available": False,
              "source": None, "capturedAt": None, "warning": None}
    if player:
        manager = registry.get_manager(str(server["id"]))
        pattern = re.compile(ServerManager._LOG_PREFIX + ServerManager._SYSTEM_CHAT
                             + re.escape(name) + r" has the following entity data: (\{.*\})$")
        try:
            reply = manager.query_command(f"data get entity {name}", pattern)
            if reply and len(reply.group(1)) <= MAX_NBT_BYTES:
                data = nbtlib.parse_nbt(reply.group(1))
                return {**result, **normalize(data), "available": True,
                        "source": "live", "capturedAt": iso_z_now()}
        except (RuntimeError, ValueError, TypeError, KeyError, IndexError, RecursionError):
            pass
        result["warning"] = "The live query did not return readable data. Showing the last save if available."
    saved = _saved_data(install, server, uid)
    if saved:
        data, saved_at = saved
        return {**result, **data, "available": True, "source": "saved", "capturedAt": saved_at}
    return result


def action_command(name, payload):
    """Validate before touching the console. Never accept raw commands/NBT."""
    valid_name(name)
    if not isinstance(payload, dict):
        raise ValueError("Expected an action object.")
    action = payload.get("action")
    if action == "heal":
        return f"effect give {name} minecraft:instant_health 1 10 true"
    if action == "feed":
        return f"effect give {name} minecraft:saturation 1 10 true"
    if action == "clear_effects":
        return f"effect clear {name}"
    if action == "gamemode":
        mode = payload.get("mode")
        if mode not in GAME_MODES:
            raise ValueError("Choose survival, creative, adventure or spectator.")
        return f"gamemode {mode} {name}"
    if action == "teleport_player":
        target = valid_name(payload.get("target"))
        return f"tp {name} {target}"
    if action == "teleport":
        dimension = payload.get("dimension")
        if not isinstance(dimension, str) or len(dimension) > 256 or not DIMENSION_RE.fullmatch(dimension):
            raise ValueError("Use a dimension ID, such as minecraft:overworld.")
        coords = []
        for axis in ("x", "y", "z"):
            raw = payload.get(axis)
            value = _number(raw)
            if isinstance(raw, bool) or value is None or abs(value) > 29_999_984:
                raise ValueError("Coordinates must be finite numbers within ±29,999,984.")
            # Vanilla centres integer X/Z coordinates on the block (+0.5).
            # Keep a decimal point so the coordinates entered in the card are
            # used exactly, including zero and negative integers.
            coordinate = format(value, ".8f").rstrip("0")
            coords.append(coordinate + "0" if coordinate.endswith(".") else coordinate)
        return f"execute in {dimension} run tp {name} {' '.join(coords)}"
    raise ValueError("Unknown player action.")


def perform_action(registry, server, name, payload):
    command = action_command(name, payload)
    if registry.get_status(str(server["id"])).get("status") != "running":
        raise service.ServerStateError("Start the server before using player actions.")
    names = {p["name"].lower() for p in live.list_online(registry, server)}
    if name.lower() not in names:
        raise service.ServerStateError("This player is offline. Saved player data is read-only.")
    if payload["action"] == "teleport_player" and payload["target"].lower() not in names:
        raise service.ServerStateError("The destination player is offline.")
    service._send(registry, str(server["id"]), command)
    # A successful stdin write is not a confirmed game effect. The UI says
    # 'command sent' and offers Refresh, rather than falsely claiming success.
    return {"sent": True, "action": payload["action"], "name": name}
