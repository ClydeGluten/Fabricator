import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.server import storage
from backend.server.players import service
from backend.server.players.mojang import PlayerNotFound


@pytest.fixture(autouse=True)
def _current_backend_modules():
    import importlib
    global service, storage, PlayerNotFound
    service = importlib.import_module("backend.server.players.service")
    storage = importlib.import_module("backend.server.storage")
    PlayerNotFound = importlib.import_module("backend.server.players.mojang").PlayerNotFound


@pytest.fixture
def whitelist_server(tmp_servers_root, monkeypatch):
    root = Path(tmp_servers_root)
    install = root / "servers" / "srv_white"
    install.mkdir()
    (root / "servers.json").write_text(json.dumps([{
        "id": "srv_white", "installPath": "srv_white", "onlineMode": False,
        "whitelist": False, "enforceWhitelist": True, "status": "stopped",
    }]))
    (install / "server.properties").write_text("white-list=false\nenforce-whitelist=true\nmotd=Hello\n")
    registry = MagicMock()
    registry.resolve_install_path.return_value = install
    registry.get_status.return_value = {"status": "stopped"}
    registry.send_command.return_value = {"success": True}
    monkeypatch.setattr("backend.server.players.routes._registry", lambda: registry)
    return install, registry


@pytest.mark.parametrize("running", [False, True])
def test_enable_persists_correct_property_without_changing_enforcement(client, whitelist_server, running):
    install, registry = whitelist_server
    if running:
        registry.get_status.return_value = {"status": "running", "startedAt": 123.0}
    response = client.patch("/api/servers/srv_white/players/whitelist/active", json={"active": True})
    assert response.status_code == 200
    assert storage.get_server("srv_white")["whitelist"] is True
    assert storage.get_server("srv_white")["enforceWhitelist"] is True
    props = (install / "server.properties").read_text()
    assert "white-list=true" in props and "enforce-whitelist=true" in props and "motd=Hello" in props
    # A new process/cache reads the persisted whitelist flag.
    fresh_cache = service.WhitelistActiveCache()
    assert fresh_cache.get(registry, storage.get_server("srv_white")) is True
    if running:
        registry.send_command.assert_called_with("srv_white", "whitelist on")


def test_false_property_does_not_inherit_enforce_true(client, whitelist_server):
    response = client.get("/api/servers/srv_white/players/state")
    assert response.json["enforceWhitelist"] is True
    assert response.json["whitelistActive"] is False


@pytest.mark.parametrize("value", ["false", 1, None, [], {}])
def test_whitelist_toggle_rejects_non_boolean(client, whitelist_server, value):
    response = client.patch("/api/servers/srv_white/players/whitelist/active", json={"active": value})
    assert response.status_code == 400


def test_batch_add_offline_names_deduplicates_and_reloads(client, whitelist_server):
    install, registry = whitelist_server
    registry.get_status.return_value = {"status": "running"}
    response = client.post("/api/servers/srv_white/players/whitelist/batch", json={"names": ["Steve", "steve", "Alex"]})
    assert response.status_code == 200
    assert len(response.json["results"]) == 2
    entries = json.loads((install / "whitelist.json").read_text())
    assert {e["name"] for e in entries} == {"Steve", "Alex"}
    registry.send_command.assert_called_once_with("srv_white", "whitelist reload")


def test_invalid_batch_is_rejected_before_any_writes(client, whitelist_server):
    install, registry = whitelist_server
    response = client.post("/api/servers/srv_white/players/whitelist/batch", json={"names": ["Steve", "@a"]})
    assert response.status_code == 400
    assert not (install / "whitelist.json").exists()
    registry.send_command.assert_not_called()


def test_batch_reports_account_lookup_failures_per_name(client, whitelist_server, monkeypatch):
    install, registry = whitelist_server
    storage.update_server("srv_white", {"onlineMode": True})
    def lookup(path, name):
        if name == "Missing":
            raise PlayerNotFound(name)
        return "11111111-2222-3333-4444-555555555555"
    monkeypatch.setattr(service, "mojang_resolve_name", lookup)
    response = client.post("/api/servers/srv_white/players/whitelist/batch", json={"names": ["Steve", "Missing"]})
    assert response.json["results"][0]["added"]
    assert response.json["results"][1]["added"] is False
    assert len(json.loads((install / "whitelist.json").read_text())) == 1
