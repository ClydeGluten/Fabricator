"""Player-card acceptance tests: saved/live data, actions and isolation."""
import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock

import nbtlib
import pytest

from backend.server.manager import ServerManager
from backend.server.players import details


@pytest.fixture(autouse=True)
def _current_backend_modules():
    # test_app_factory deliberately removes backend.* from sys.modules.
    # Route tests must patch the same module objects as the new Flask app.
    import importlib
    global details, ServerManager
    details = importlib.import_module("backend.server.players.details")
    ServerManager = importlib.import_module("backend.server.manager").ServerManager

UID = "11111111-2222-3333-4444-555555555555"
SNBT = '''{Pos:[12.5d,64d,-20d],Dimension:"minecraft:overworld",Health:13.5f,
 foodLevel:16,foodSaturationLevel:2.5f,XpLevel:7,playerGameType:0,
 Inventory:[{Slot:0b,id:"minecraft:diamond",count:3,components:{"minecraft:custom_name":"Treasure"}},
 {Slot:12b,id:"example:modded_item",count:2}],
 equipment:{head:{id:"minecraft:iron_helmet",count:1}},
 EnderItems:[{Slot:4b,id:"minecraft:ender_pearl",count:8}]}'''


@pytest.fixture
def saved_player(tmp_servers_root, monkeypatch):
    root = Path(tmp_servers_root)
    install = root / "servers" / "srv_test"
    install.mkdir()
    server = {"id": "srv_test", "name": "Test", "installPath": "srv_test", "loader": "fabric",
              "version": "26.3", "status": "stopped", "onlineMode": True, "levelName": "world"}
    (root / "servers.json").write_text(json.dumps([server]))
    (install / "usercache.json").write_text(json.dumps([{"name": "Steve", "uuid": UID}]))
    (install / "server.properties").write_text("level-name=My World\n")
    world = install / "My World" / "players/data"
    world.mkdir(parents=True)
    path = world / f"{UID}.dat"
    nbtlib.File(nbtlib.parse_nbt(SNBT), gzipped=True).save(path)
    os.utime(path, (1600000000, 1600000000))
    registry = MagicMock()
    registry.resolve_install_path.return_value = install
    registry.get_status.return_value = {"status": "stopped"}
    monkeypatch.setattr(details.live, "list_online", lambda *_: [])
    monkeypatch.setattr("backend.server.players.routes._registry", lambda: registry)
    return install, server, registry


def test_saved_card_reads_actual_level_name_and_26_layout(client, saved_player):
    install, server, registry = saved_player
    before = (install / "My World/players/data" / f"{UID}.dat").read_bytes()
    result = client.get("/api/servers/srv_test/players/Steve/details")
    assert result.status_code == 200
    data = result.json
    assert data["source"] == "saved" and not data["online"]
    assert data["capturedAt"].startswith("2020-09-13")
    assert data["position"] == {"x": 12.5, "y": 64, "z": -20}
    assert data["food"] == 16 and data["health"] == 13.5
    assert data["equipment"][0]["slot"] == "head"
    assert data["inventory"][1]["id"] == "example:modded_item"
    assert data["enderChest"][0]["count"] == 8
    assert (install / "My World/players/data" / f"{UID}.dat").read_bytes() == before
    registry.send_command.assert_not_called()


def test_classic_format_and_negative_offhand_slot():
    data = details.normalize(nbtlib.parse_nbt('''{Pos:[1d,2d,3d],Dimension:-1,playerGameType:1,
      Inventory:[{Slot:0b,id:"minecraft:stone",Count:64b},{Slot:103b,id:"minecraft:diamond_helmet",Count:1b},
      {Slot:-106b,id:"minecraft:shield",Count:1b}]}'''))
    assert data["gameMode"] == "creative"
    assert data["dimension"] == "minecraft:the_nether"
    assert len(data["inventory"]) == 1 and data["inventory"][0]["count"] == 64
    assert {i["slot"] for i in data["equipment"]} == {"head", "offhand"}


def test_latest_save_across_layouts_wins(saved_player):
    install, server, registry = saved_player
    classic = install / "My World/playerdata"
    classic.mkdir()
    nbtlib.File(nbtlib.parse_nbt('{Health:8f}'), gzipped=True).save(classic / f"{UID}.dat")
    data = details.get_details(registry, server, "Steve")
    assert data["health"] == 8


def test_live_read_and_failed_live_fallback(saved_player, monkeypatch):
    _, server, registry = saved_player
    monkeypatch.setattr(details.live, "list_online", lambda *_: [{"name": "Steve", "uuid": UID}])
    manager = registry.get_manager.return_value
    line = '[10:00:00] [Server thread/INFO]: System chat: Steve has the following entity data: {Health:20f,foodLevel:20}'
    manager.query_command.side_effect = lambda command, pattern: pattern.search(line)
    result = details.get_details(registry, server, "steve")
    assert result["source"] == "live" and result["online"] and result["health"] == 20
    assert manager.query_command.call_args.args[0] == "data get entity Steve"
    manager.query_command.side_effect = lambda *_: None
    result = details.get_details(registry, server, "Steve")
    assert result["source"] == "saved" and result["online"]
    assert result["warning"]


def test_chat_cannot_spoof_live_snapshot(saved_player, monkeypatch):
    _, server, registry = saved_player
    monkeypatch.setattr(details.live, "list_online", lambda *_: [{"name": "Steve", "uuid": UID}])
    text = '[10:00:00] [Server thread/INFO]: <Griefer> Steve has the following entity data: {Health:999f}'
    registry.get_manager.return_value.query_command.side_effect = lambda c, p: p.search(text)
    assert details.get_details(registry, server, "Steve")["source"] == "saved"


def test_new_player_is_not_reported_as_empty_inventory(saved_player):
    _, server, registry = saved_player
    data = details.get_details(registry, server, "NewPlayer")
    assert data["available"] is False and data["source"] is None
    assert "inventory" not in data


def test_player_file_symlink_cannot_escape_server(saved_player, tmp_path):
    install, server, registry = saved_player
    path = install / "My World/players/data" / f"{UID}.dat"
    outside = tmp_path / "outside.dat"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        details.get_details(registry, server, "Steve")


@pytest.mark.parametrize("name", ["@a", "Steve\nstop", "Steve\r", "../user", "A" * 17])
def test_reject_unsafe_player_names(name):
    with pytest.raises(ValueError):
        details.action_command(name, {"action": "heal"})


@pytest.mark.parametrize("payload", [
    {"action": "teleport", "dimension": "minecraft:overworld\nstop", "x": 0, "y": 64, "z": 0},
    {"action": "teleport", "dimension": "minecraft:overworld", "x": "nan", "y": 64, "z": 0},
    {"action": "teleport", "dimension": "minecraft:overworld", "x": True, "y": 64, "z": 0},
    {"action": "teleport", "dimension": "minecraft:overworld", "x": 30000000, "y": 64, "z": 0},
    {"action": "teleport_player", "target": "@a"},
    {"action": "gamemode", "mode": "creative\nstop"}, {"action": "kill"}, None,
])
def test_reject_unsafe_actions(payload):
    with pytest.raises(ValueError):
        details.action_command("Steve", payload)


def test_coordinate_teleport_is_dimension_aware():
    cmd = details.action_command("Steve", {"action": "teleport", "x": 0, "y": 65.5, "z": -125,
                                            "dimension": "minecraft:the_nether"})
    assert cmd == "execute in minecraft:the_nether run tp Steve 0.0 65.5 -125.0"


def test_online_actions_and_offline_rejection(client, saved_player, monkeypatch):
    _, _, registry = saved_player
    registry.get_status.return_value = {"status": "running"}
    response = client.post("/api/servers/srv_test/players/Steve/actions", json={"action": "heal"})
    assert response.status_code == 409
    registry.send_command.assert_not_called()
    monkeypatch.setattr(details.live, "list_online", lambda *_: [{"name": "Steve", "uuid": UID}])
    registry.send_command.return_value = {"success": True}
    response = client.post("/api/servers/srv_test/players/Steve/actions", json={"action": "feed"})
    assert response.status_code == 200 and response.json["sent"]
    registry.send_command.assert_called_with("srv_test", "effect give Steve minecraft:saturation 1 10 true")
    response = client.post("/api/servers/srv_test/players/Steve/actions", json={"action": "teleport_player", "target": "Alex"})
    assert response.status_code == 409


def test_player_routes_require_panel_login(auth_client):
    assert auth_client.get("/api/servers/x/players/Steve/details").status_code == 401
    assert auth_client.post("/api/servers/x/players/Steve/actions", json={"action": "heal"}).status_code == 401
    assert auth_client.post("/api/servers/x/players/whitelist/batch", json={"names": ["Steve"]}).status_code == 401


def test_console_query_sees_immediate_reply_not_history(tmp_path):
    manager = ServerManager(str(tmp_path))
    manager._append_stdout("reply: old")
    def send(command):
        manager._append_stdout("reply: fresh")
        return {"success": True}
    manager.send_command = send
    assert manager.query_command("test", re.compile(r"^reply: (.*)$")).group(1) == "fresh"
    manager.send_command = lambda _: {"success": True}
    assert manager.query_command("test", re.compile("reply"), timeout=0.01) is None
