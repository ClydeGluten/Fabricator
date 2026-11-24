"""Disposable panel for browser acceptance tests; never opens real server data.

The fake Minecraft process exercises the real Flask routes and NBT reader. A
real game-server integration test is separate from this deterministic UI test.
"""
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nbtlib

tmp = tempfile.TemporaryDirectory(prefix="fabricator-browser-")
root = Path(tmp.name)
for key, value in {
    "SERVER_ROOT": root / "servers", "SERVER_INDEX_FILE": root / "servers.json",
    "JAVA_ROOT": root / "java", "BACKUPS_DIR": root / "backups",
    "FABRICATOR_DISABLE_AUTH": "1", "FABRICATOR_DISABLE_SCHEDULER": "1",
    "FABRICATOR_DISABLE_SELF_UPDATE": "1", "FLASK_ENV": "development",
}.items():
    os.environ[key] = str(value)

from backend.core.app import create_app
from backend.server.registry import get_server_process_registry
from backend.server.manager import ServerManager, OnlinePlayer

UID = "11111111-2222-3333-4444-555555555555"
snapshot = nbtlib.parse_nbt('''{Pos:[12.5d,64d,-20d],Dimension:"minecraft:overworld",Health:13.5f,
foodLevel:16,XpLevel:7,playerGameType:0,Inventory:[{Slot:0b,id:"minecraft:diamond",count:3},
{Slot:12b,id:"example:modded_item",count:2}],equipment:{head:{id:"minecraft:iron_helmet",count:1}},
EnderItems:[{Slot:4b,id:"minecraft:ender_pearl",count:8}]}''')


class FixtureManager(ServerManager):
    def __init__(self, path):
        super().__init__(str(path))
        self._players["Steve"] = OnlinePlayer("Steve", datetime.now(timezone.utc), UID)
        self.commands = []

    def status(self):
        return {"status": "running", "players": 1, "cpu": 0, "memory": 128}

    def send_command(self, command):
        self.commands.append(command)
        if command.startswith("effect give Steve minecraft:instant_health"):
            snapshot["Health"] = nbtlib.Float(20)
        if command.startswith("effect give Steve minecraft:saturation"):
            snapshot["foodLevel"] = nbtlib.Int(20)
        if command.startswith("data get entity Steve"):
            self._append_stdout(f"[10:00:00] [Server thread/INFO]: System chat: Steve has the following entity data: {snapshot.snbt()}")
        return {"success": True}


records = []
for suffix in ("offline", "live"):
    sid = f"srv_{suffix}"
    path = root / "servers" / sid
    (path / "world/players/data").mkdir(parents=True)
    (path / "mods").mkdir()
    (path / "server.properties").write_text("level-name=world\nwhite-list=false\n")
    (path / "usercache.json").write_text(json.dumps([{"name": "Steve", "uuid": UID}]))
    nbtlib.File(snapshot, gzipped=True).save(path / "world/players/data" / f"{UID}.dat")
    records.append({"id": sid, "name": f"Browser fixture ({suffix})", "loader": "fabric", "version": "26.3",
                    "port": 25565, "memory": "1G", "maxPlayers": 5, "status": "stopped",
                    "onlineMode": False, "whitelist": False, "enforceWhitelist": False, "installPath": sid})
(root / "servers.json").write_text(json.dumps(records))
app = create_app()
registry = get_server_process_registry()
manager = FixtureManager(root / "servers/srv_live")
registry._instances["srv_live"] = manager
registry._started_at["srv_live"] = 123.0


@app.get("/test/commands")
def commands():
    return {"commands": manager.commands}


def stop(*_):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, stop)
try:
    app.run(host="127.0.0.1", port=5057, debug=False, use_reloader=False)
finally:
    tmp.cleanup()
