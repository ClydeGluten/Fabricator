"""Session-authenticated local instance synchronization endpoints."""
from flask import Blueprint, jsonify, request

from backend.modrinth import instance_sync as sync
from backend.modrinth.client import ModrinthClient
from backend.utils.routes import require_server, with_server_lock

instance_sync_bp = Blueprint("instance_sync", __name__, url_prefix="/api/servers/<server_id>/modrinth-sync")
modrinth_client = ModrinthClient()


def _registry():
    from backend.server.registry import get_server_process_registry
    return get_server_process_registry()


@instance_sync_bp.errorhandler(sync.SyncError)
def sync_error(exc):
    return jsonify(error=str(exc)), exc.status


@instance_sync_bp.errorhandler(OSError)
def io_error(exc):
    return jsonify(error="Cannot access instance/server files. Check the folder permissions and free disk space."), 409


@instance_sync_bp.get("")
@require_server
def status(server_id, server):
    result = sync.list_instances()
    state = server.get("modrinthSync") or {}
    return jsonify(**result, instance=state.get("instance"), lastSyncAt=state.get("lastSyncAt"),
                   supported=str(server.get("loader") or "").lower() in sync.SUPPORTED_LOADERS)


@instance_sync_bp.post("/preview")
@require_server
@with_server_lock
def preview(server_id, server):
    from backend.server import storage
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise sync.SyncError("Expected a JSON object.")
    server = storage.get_server(server_id)  # fresh after acquiring the lock
    result = sync.preview(server, _registry().resolve_install_path(server), data.get("instance"), modrinth_client)
    return jsonify(result)


@instance_sync_bp.post("/apply")
@require_server
@with_server_lock
def apply(server_id, server):
    from backend.server import storage
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise sync.SyncError("Expected a JSON object.")
    server = storage.get_server(server_id)
    def stopped():
        current = storage.get_server(server_id) or {}
        return (current.get("status") not in {"running", "starting", "stopping", "installing"}
                and _registry().get_status(server_id).get("status") == "stopped")
    return jsonify(sync.apply(server, _registry().resolve_install_path(server), data.get("planToken"), stopped))
