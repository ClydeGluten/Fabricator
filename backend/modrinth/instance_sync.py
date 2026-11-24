"""Explicit, one-way sync from read-only Modrinth instances to stopped servers.

Plans are kept on the server, expire, and are revalidated by file contents before
application. Only files previously managed by sync are pruned when absent from
the source. Other server-only mods survive. Classification intentionally differs
from modpack import: server-optional mods are retained, and class references are
not evidence that a universal mod is client-only.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import tempfile
import threading
import time
import zipfile

from backend.modrinth import installed, modmeta
from backend.modrinth.client import ModrinthApiError
from backend.utils.time import iso_z_now

SUPPORTED_LOADERS = {"fabric", "quilt", "forge", "neoforge"}
MARKER = ".modrinth-sync-in-progress.json"
MAX_JARS = 2000
PLAN_TTL = 15 * 60
_plans: OrderedDict = OrderedDict()
_lock = threading.Lock()


class SyncError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class Jar:
    name: str
    sha1: str
    sha256: str
    size: int
    ids: set
    side: str
    reason: str
    title: str
    loaders: set


def profiles_root() -> Path | None:
    value = os.environ.get("FABRICATOR_MODRINTH_PROFILES", "").strip()
    return Path(value).expanduser().resolve() if value else None


def _name(value):
    if (not isinstance(value, str) or not value or value in {".", ".."}
            or len(value) > 255 or any(c in value for c in "/\\")
            or any(ord(c) < 32 for c in value)):
        raise SyncError("Choose an instance from the list.")
    return value


def list_instances():
    root = profiles_root()
    if root is None:
        return {"configured": False, "instances": []}
    if not root.is_dir():
        raise SyncError("The Modrinth profiles folder is unavailable. Check its read-only mount.", 409)
    rows = []
    for folder in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if folder.name.startswith(".") or folder.is_symlink() or not folder.is_dir():
            continue
        mods = folder / "mods"
        if mods.is_symlink():
            continue
        count = sum(p.is_file() and not p.is_symlink() and p.name.lower().endswith(".jar")
                    for p in mods.iterdir()) if mods.is_dir() else 0
        rows.append({"id": folder.name, "name": folder.name, "modCount": count})
    return {"configured": True, "instances": rows}


def source_folder(instance):
    root = profiles_root()
    if root is None:
        raise SyncError("Connect the Modrinth profiles folder first.", 409)
    folder = root / _name(instance)
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent != root:
        raise SyncError("Instance not found in the connected Modrinth folder.", 404)
    mods = folder / "mods"
    if mods.is_symlink() or not mods.is_dir():
        raise SyncError("This instance has no accessible mods folder yet.", 409)
    return mods


def _hash(path):
    # Never follow a jar symlink (including one swapped in while scanning).
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 512 * 1024 * 1024:
            raise SyncError(f"Not a regular mod jar, or larger than 512 MiB: {path.name}")
        sha1, sha256 = hashlib.sha1(), hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            sha1.update(chunk)
            sha256.update(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise SyncError("Files changed while reading. Wait for Modrinth to finish, then preview again.", 409)
    return sha1.hexdigest(), sha256.hexdigest(), after.st_size


def _metadata(path):
    ids, loaders, title, side, reason = set(), set(), path.name, "unknown", "No explicit side metadata"
    try:
        with zipfile.ZipFile(path) as archive:
            def read(name):
                if archive.getinfo(name).file_size > 2 * 1024 * 1024:
                    raise SyncError(f"Oversized mod manifest: {path.name}")
                return archive.read(name)

            names = set(archive.namelist())
            if "fabric.mod.json" in names:
                raw = read("fabric.mod.json")
                # Gson used by Fabric accepts literal newlines/tabs in strings;
                # some published mods (e.g. BetterGrassify) contain these.
                meta = json.loads(raw, strict=False)
                if not isinstance(meta, dict):
                    raise ValueError("Invalid manifest")
                ids |= modmeta._read_fabric_json(json.dumps(meta).encode())[0]
                loaders.add("fabric")
                title = str(meta.get("name") or title)
                env = meta.get("environment", "*")
                if env == "client":
                    side, reason = "client", "fabric.mod.json: environment=client"
                elif env == "server":
                    side, reason = "server", "fabric.mod.json: environment=server"
                # '*' says the loader permits both sides, not that the author
                # implemented both. Modrinth may still explicitly say client_only.
            if "quilt.mod.json" in names:
                raw = read("quilt.mod.json")
                meta = json.loads(raw, strict=False)
                ids |= modmeta._read_quilt_json(json.dumps(meta).encode())[0]
                loaders.add("quilt")
                block = meta.get("quilt_loader") or {}
                env = (meta.get("minecraft") or block.get("minecraft") or {}).get("environment")
                if env == "client":
                    side, reason = "client", "quilt.mod.json: environment=client"
                elif env == "dedicated_server" and side != "client":
                    side, reason = "server", "quilt.mod.json: dedicated_server"
            for name, loader in (("META-INF/neoforge.mods.toml", "neoforge"), ("META-INF/mods.toml", "forge")):
                if name in names:
                    raw = read(name)
                    ids |= modmeta._read_forge_toml(raw)[0]
                    loaders.add(loader)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise SyncError(f"Cannot read mod jar: {path.name}") from exc
    except (UnicodeError, ValueError, AttributeError, TypeError) as exc:
        if isinstance(exc, SyncError):
            raise
        # An unknown manifest is not proof of client-only status. The exact
        # hash can still be identified by Modrinth; otherwise show a warning.
        return ids, "unknown", "Unrecognized jar manifest; no reliable local side metadata", title, loaders
    return ids, side, reason, title, loaders


def snapshot(folder):
    if folder.is_symlink():
        raise SyncError("A mods folder must not be a symbolic link.")
    if not folder.exists():
        return {}
    rows = {}
    for path in sorted(folder.iterdir()):
        if not path.name.lower().endswith((".jar", ".jar.disabled")):
            continue
        if path.is_symlink() or not path.is_file():
            raise SyncError(f"Mod must be a regular file: {path.name}")
        if len(rows) >= MAX_JARS:
            raise SyncError(f"At most {MAX_JARS} jars can be synced at once.")
        sha1, sha256, size = _hash(path)
        ids, side, reason, title, loaders = _metadata(path)
        rows[path.name] = Jar(path.name, sha1, sha256, size, ids, side, reason, title, loaders)
    return rows


def fingerprint(rows):
    return {name: jar.sha256 for name, jar in rows.items()}


def classify(jar, project):
    if jar.side == "client":
        return jar.side, jar.reason
    tags = project.get("environment") or []
    if isinstance(tags, str):
        tags = [tags]
    tags = {tag for tag in tags if isinstance(tag, str)} if isinstance(tags, list) else set()
    server_tags = {"client_and_server", "client_or_server", "client_or_server_prefers_both",
                   "client_only_server_optional", "dedicated_server_only", "server_only",
                   "server_only_client_optional"}
    if tags & server_tags:
        return "server", "Modrinth: " + ", ".join(sorted(tags & server_tags))
    if tags & {"client_only", "singleplayer_only"}:
        return "client", "Modrinth: " + ", ".join(sorted(tags))
    side = project.get("server_side")
    if side == "unsupported":
        return "client", "Modrinth: server_side=unsupported"
    if side in {"optional", "required"}:
        return "server", f"Modrinth: server_side={side}"
    return jar.side, jar.reason


def _same_mod(a, b, versions):
    left = versions.get(a.sha1, {}).get("project_id")
    right = versions.get(b.sha1, {}).get("project_id")
    return a.name == b.name or a.sha256 == b.sha256 or bool(a.ids & b.ids) or bool(left and left == right)


def preview(server, install, instance, client):
    loader = str(server.get("loader") or "").lower()
    if loader not in SUPPORTED_LOADERS:
        raise SyncError("Instance sync supports Fabric, Quilt, Forge and NeoForge servers.")
    install = Path(install).resolve()
    if (install / MARKER).exists():
        raise SyncError("An interrupted sync needs recovery first; see the mod-sync-backups folder.", 409)
    source = source_folder(instance)
    destination = install / "mods"
    if source.resolve() == destination.resolve():
        raise SyncError("The instance and server must have different mods folders.")
    origin, target = snapshot(source), snapshot(destination)
    warnings, conflicts = [], []
    versions, projects = {}, {}
    try:
        versions = client.get_versions_by_hashes(list(dict.fromkeys(j.sha1 for j in [*origin.values(), *target.values()]))) if origin or target else {}
        projects = installed.resolve_projects(client, [v["project_id"] for v in versions.values() if v.get("project_id")])
    except ModrinthApiError:
        warnings.append("Modrinth lookup is unavailable. Only explicit jar metadata can identify client-only mods; unknown mods are included.")
    included, skipped, disabled = {}, [], []
    for name, jar in origin.items():
        if name.lower().endswith(".disabled"):
            disabled.append(name)
            continue
        version = versions.get(jar.sha1, {})
        project = projects.get(version.get("project_id"), {})
        side, reason = classify(jar, project)
        item = {"filename": name, "title": project.get("title") or jar.title, "side": side,
                "reason": reason, "version": version.get("version_number"), "size": jar.size}
        if side == "client":
            skipped.append(item)
            continue
        compatible = {loader, "fabric"} if loader == "quilt" else {loader}
        known_loaders = set(version.get("loaders") or jar.loaders)
        if known_loaders and not known_loaders & compatible:
            conflicts.append(f"{name}: loader {', '.join(sorted(known_loaders))} does not match {loader}.")
        game_versions = version.get("game_versions") or []
        if game_versions and server.get("version") and server["version"] not in game_versions:
            # Authors' advertised version lists can lag compatible patches.
            # Do not refuse an exact file the user's instance already uses.
            warnings.append(f"{name}: Modrinth does not list Minecraft {server['version']} for this file; check compatibility before starting.")
        included[name] = item
    # Two active versions of the same mod in the client are not a valid sync source.
    names = list(included)
    for i, name in enumerate(names):
        for other in names[i + 1:]:
            if _same_mod(origin[name], origin[other], versions):
                conflicts.append(f"Duplicate source mod: {name} and {other}.")

    previous = server.get("modrinthSync") or {}
    managed = previous.get("managed") or {}
    removals, writes, unchanged, preserved = {}, {}, [], []
    for name, item in included.items():
        jar = origin[name]
        matches = [old for old in target.values() if _same_mod(jar, old, versions)]
        item["replaces"] = [old.name for old in matches if old.name != name or old.sha256 != jar.sha256]
        exact = target.get(name)
        if exact and exact.sha256 == jar.sha256:
            unchanged.append(item)
        else:
            writes[name] = {**item, "action": "replace" if matches else "add"}
        for old in matches:
            if old.name != name:
                removals[old.name] = "Replaced by " + name
            if old.name in managed and old.sha256 != managed[old.name] and old.sha256 != jar.sha256:
                conflicts.append(f"{old.name}: changed on the server since the last sync; resolve the change before syncing.")

    for name, digest in managed.items():
        if name not in target or name in included or name in removals:
            continue
        if target[name].sha256 != digest:
            conflicts.append(f"{name}: locally modified managed mod would be removed; resolve it first.")
        else:
            removals[name] = "Previously synced mod is no longer enabled for this server in the instance"
    for name in target:
        if name not in included and name not in removals:
            preserved.append(name)
    if not included:
        warnings.append("No server mods are enabled in this instance. Previously synced mods will be removed if you apply.")
    token = secrets.token_urlsafe(24)
    data = {"planToken": token, "instance": instance, "expiresIn": PLAN_TTL,
            "changes": list(writes.values()) + [{"filename": n, "action": "remove", "reason": r} for n, r in removals.items()],
            "unchanged": unchanged, "skipped": skipped, "disabled": disabled,
            "preserved": preserved, "warnings": warnings, "conflicts": conflicts,
            "unknown": [item["filename"] for item in included.values() if item["side"] == "unknown"]}
    entries = {}
    for name in included:
        # Also pin unrecognised jars so a later successful hash lookup cannot
        # silently auto-update them away from the instance's exact files.
        entries[name] = {"pinned": True}
        version = versions.get(origin[name].sha1, {})
        project = projects.get(version.get("project_id"), {})
        if version.get("project_id"):
            entries[name] = {"projectId": version["project_id"], "versionId": version.get("id"),
                             "versionNumber": version.get("version_number"), "title": project.get("title"),
                             "slug": project.get("slug"), "iconUrl": project.get("icon_url"), "pinned": True}
    plan = {"serverId": server["id"], "install": install, "instance": instance,
            "source": source, "origin": fingerprint(origin), "target": fingerprint(target),
            "writes": writes, "removals": removals, "managed": {n: origin[n].sha256 for n in included},
            "entries": entries, "previous": previous, "loader": loader, "version": server.get("version"),
            "conflicts": conflicts, "expires": time.monotonic() + PLAN_TTL}
    with _lock:
        for key in list(_plans):
            if _plans[key]["expires"] < time.monotonic():
                _plans.pop(key)
        while len(_plans) >= 32:
            _plans.popitem(last=False)
        _plans[token] = plan
    return data


def apply(server, install, token, is_stopped):
    from backend.server import storage
    if not isinstance(token, str):
        raise SyncError("Preview the sync before applying it.")
    with _lock:
        plan = _plans.get(token)
    if not plan or plan["serverId"] != server["id"] or plan["expires"] < time.monotonic():
        raise SyncError("The preview has expired. Preview again.", 409)
    if plan["conflicts"]:
        raise SyncError("Resolve the conflicts shown in the preview first.", 409)
    install = Path(install).resolve()
    if (install != plan["install"] or server.get("version") != plan["version"]
            or str(server.get("loader", "")).lower() != plan["loader"]
            or (server.get("modrinthSync") or {}) != plan["previous"]):
        raise SyncError("Server settings changed. Preview again.", 409)
    if not is_stopped():
        raise SyncError("Stop the Minecraft server before applying mod changes.", 409)
    marker = install / MARKER
    if marker.exists() or marker.is_symlink():
        raise SyncError("An interrupted sync needs recovery first.", 409)
    source = source_folder(plan["instance"])
    mods = install / "mods"
    if (source != plan["source"] or fingerprint(snapshot(source)) != plan["origin"]
            or fingerprint(snapshot(mods)) != plan["target"]):
        raise SyncError("Instance or server files changed. Preview again.", 409)

    backups = install / "mod-sync-backups"
    if backups.is_symlink():
        raise SyncError("The sync backup directory must not be a symbolic link.")
    backups.mkdir(exist_ok=True)
    backup = backups / (time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(4))
    backup.mkdir(mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".modrinth-sync-", dir=install))
    old_moved = new_moved = False
    old_manifest = server.get(storage.CONTENT_MANIFEST_KEY) or {}
    try:
        if mods.exists():
            shutil.copytree(mods, staging / "mods", symlinks=True)
        else:
            (staging / "mods").mkdir()
        for name in plan["removals"]:
            (staging / "mods" / name).unlink()
        for name in plan["writes"]:
            shutil.copyfile(source / name, staging / "mods" / name, follow_symlinks=False)
            if (staging / "mods" / name).is_symlink() or _hash(staging / "mods" / name)[1] != plan["origin"][name]:
                raise SyncError("The instance changed while copying. Preview again.", 409)
        if (fingerprint(snapshot(mods)) != plan["target"]
                or fingerprint(snapshot(source)) != plan["origin"] or not is_stopped()):
            raise SyncError("Files or server state changed while preparing sync. Preview again.", 409)
        record = {"instance": plan["instance"], "createdAt": iso_z_now(), "modsExisted": mods.exists(),
                  "previousModContent": old_manifest, "previousSync": plan["previous"]}
        (backup / "before.json").write_text(json.dumps(record, indent=2))
        marker.write_text(json.dumps({"backup": backup.name}))
        if mods.exists():
            os.replace(mods, backup / "mods")
            old_moved = True
        os.replace(staging / "mods", mods)
        new_moved = True
        manifest = {k: v for k, v in old_manifest.items() if k not in plan["removals"] and k not in plan["writes"]}
        manifest.update(plan["entries"])
        state = {"instance": plan["instance"], "managed": plan["managed"], "lastSyncAt": iso_z_now(), "backup": backup.name}
        if storage.update_server(server["id"], {storage.CONTENT_MANIFEST_KEY: manifest, "modrinthSync": state}) is None:
            raise SyncError("Server was removed during sync.", 409)
    except Exception:
        if new_moved:
            os.replace(mods, staging / "failed-mods")
        if old_moved:
            os.replace(backup / "mods", mods)
        marker.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    marker.unlink()
    with _lock:
        _plans.pop(token, None)
    return {"synced": True, "instance": plan["instance"], "lastSyncAt": state["lastSyncAt"],
            "copied": len(plan["writes"]), "removed": len(plan["removals"]),
            "backup": str(Path("mod-sync-backups") / backup.name)}
