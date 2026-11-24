import hashlib
import importlib
import json
from pathlib import Path
import shutil
import zipfile
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def current_modules():
    global sync, routes, storage, ApiError
    sync = importlib.import_module('backend.modrinth.instance_sync')
    routes = importlib.import_module('backend.modrinth.instance_routes')
    storage = importlib.import_module('backend.server.storage')
    ApiError = importlib.import_module('backend.modrinth.client').ModrinthApiError
    sync._plans.clear()


def jar(folder, filename, mod_id=None, env='*', version='1', extra=None):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('fabric.mod.json', json.dumps({
            'schemaVersion': 1, 'id': mod_id or filename.split('.')[0],
            'name': mod_id or filename, 'version': version, 'environment': env,
            **(extra or {}),
        }))
        # A universal mod can contain client classes. That must NOT exclude it.
        archive.writestr('example/Renderer.class', b'net/minecraft/client/ClientOnlyThing')
    return path


@pytest.fixture
def rig(tmp_servers_root, monkeypatch):
    root = Path(tmp_servers_root)
    profiles = root / 'profiles'
    source = profiles / 'Dinky Adventures' / 'mods'
    source.mkdir(parents=True)
    install = root / 'servers' / 'srv_sync'
    mods = install / 'mods'
    mods.mkdir(parents=True)
    (install / 'world').mkdir()
    (install / 'world' / 'level.dat').write_bytes(b'world untouched')
    (install / 'config').mkdir()
    (install / 'config' / 'mod.conf').write_text('configuration untouched')
    (root / 'servers.json').write_text(json.dumps([{
        'id': 'srv_sync', 'installPath': 'srv_sync', 'loader': 'fabric',
        'version': '26.3', 'status': 'stopped',
    }]))
    monkeypatch.setenv('FABRICATOR_MODRINTH_PROFILES', str(profiles))
    registry = MagicMock()
    registry.resolve_install_path.return_value = install
    registry.get_status.return_value = {'status': 'stopped'}
    monkeypatch.setattr(routes, '_registry', lambda: registry)
    api = MagicMock()
    versions, projects = {}, {}
    api.get_versions_by_hashes.side_effect = lambda hashes: {h: versions[h] for h in hashes if h in versions}
    api.get_projects.side_effect = lambda ids: [projects[i] for i in ids if i in projects]
    monkeypatch.setattr(routes, 'modrinth_client', api)

    class Rig:
        def server(self):
            return storage.get_server('srv_sync')

        def tag(self, path, environment=None, server_side=None, game_versions=None, loaders=None):
            digest = hashlib.sha1(path.read_bytes()).hexdigest()
            pid = path.stem
            versions[digest] = {'id': 'ver_' + pid, 'project_id': pid, 'version_number': '1',
                                'game_versions': game_versions or ['26.3'], 'loaders': loaders or ['fabric']}
            projects[pid] = {'id': pid, 'title': pid, 'environment': environment, 'server_side': server_side}

        def preview(self, instance='Dinky Adventures'):
            return sync.preview(self.server(), install, instance, api)

        def apply(self, plan):
            return sync.apply(self.server(), install, plan['planToken'], lambda: True)

    r = Rig()
    r.root, r.profiles, r.source, r.install, r.mods, r.api, r.registry = root, profiles, source, install, mods, api, registry
    return r


def test_all_instances_are_discovered_and_new_instances_need_no_restart(client, rig):
    response = client.get('/api/servers/srv_sync/modrinth-sync')
    assert [r['name'] for r in response.json['instances']] == ['Dinky Adventures']
    jar(rig.profiles / 'New Pack' / 'mods', 'mod.jar')
    response = client.get('/api/servers/srv_sync/modrinth-sync')
    assert [r['name'] for r in response.json['instances']] == ['Dinky Adventures', 'New Pack']
    assert response.json['instances'][1]['modCount'] == 1


def test_only_client_mods_are_skipped_and_optional_and_unknown_are_kept(rig):
    jar(rig.source, 'local-client.jar', env='client')
    rig.tag(jar(rig.source, 'api-client.jar'), ['client_only'])
    rig.tag(jar(rig.source, 'singleplayer.jar'), ['singleplayer_only'])
    rig.tag(jar(rig.source, 'optional.jar'), ['client_only_server_optional'])
    rig.tag(jar(rig.source, 'legacy-optional.jar'), server_side='optional')
    rig.tag(jar(rig.source, 'legacy-client.jar'), server_side='unsupported')
    jar(rig.source, 'unknown.jar')
    jar(rig.source, 'disabled.jar.disabled')
    plan = rig.preview()
    assert {r['filename'] for r in plan['skipped']} == {'local-client.jar', 'api-client.jar', 'singleplayer.jar', 'legacy-client.jar'}
    assert {r['filename'] for r in plan['changes']} == {'optional.jar', 'legacy-optional.jar', 'unknown.jar'}
    assert plan['unknown'] == ['unknown.jar']
    assert plan['disabled'] == ['disabled.jar.disabled']
    assert not plan['conflicts']
    before = {p.name: p.read_bytes() for p in rig.source.iterdir()}
    rig.apply(plan)
    assert {p.name for p in rig.mods.iterdir()} == {'optional.jar', 'legacy-optional.jar', 'unknown.jar'}
    assert before == {p.name: p.read_bytes() for p in rig.source.iterdir()}


def test_universal_client_entrypoint_or_client_bytecode_is_not_client_only(rig):
    jar(rig.source, 'universal.jar', extra={'entrypoints': {'client': ['example.Rendering']}})
    plan = rig.preview()
    assert not plan['skipped']
    assert plan['unknown'] == ['universal.jar']


def test_fabric_lenient_json_with_literal_newline_still_identifies_client_mod(rig):
    with zipfile.ZipFile(rig.source / 'lenient.jar', 'w') as archive:
        archive.writestr('fabric.mod.json', '{"id":"lenient","description":"line one\nline two","environment":"client"}')
    plan = rig.preview()
    assert plan['skipped'][0]['filename'] == 'lenient.jar'
    assert not plan['changes']


def test_unfamiliar_manifest_can_still_be_classified_by_exact_modrinth_hash(rig):
    path = rig.source / 'unfamiliar.jar'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('fabric.mod.json', '{"id":"unfamiliar", /* tolerated by some loaders */ "environment":"client"}')
    rig.tag(path, ['client_only'])
    assert rig.preview()['skipped'][0]['filename'] == 'unfamiliar.jar'


def test_exact_jar_client_declaration_overrides_project_server_support(rig):
    rig.tag(jar(rig.source, 'client.jar', env='client'), ['client_and_server'])
    assert rig.preview()['skipped'][0]['filename'] == 'client.jar'


def test_network_failure_is_visible_and_does_not_delete_unknown_mods(rig):
    jar(rig.source, 'client.jar', env='client')
    jar(rig.source, 'unknown.jar')
    rig.api.get_versions_by_hashes.side_effect = ApiError('offline')
    plan = rig.preview()
    assert plan['warnings'] and plan['unknown'] == ['unknown.jar']
    assert plan['skipped'][0]['filename'] == 'client.jar'


def test_replace_by_mod_identity_preserve_server_only_and_backup(rig):
    old = jar(rig.mods, 'shared-v1.jar', 'shared', version='1').read_bytes()
    jar(rig.mods, 'server-only.jar', env='server')
    new = jar(rig.source, 'shared-v2.jar', 'shared', version='2').read_bytes()
    plan = rig.preview()
    assert plan['preserved'] == ['server-only.jar']
    assert plan['changes'][0]['action'] == 'replace'
    result = rig.apply(plan)
    assert (rig.mods / 'shared-v2.jar').read_bytes() == new
    assert not (rig.mods / 'shared-v1.jar').exists()
    assert (rig.mods / 'server-only.jar').exists()
    assert (rig.install / result['backup'] / 'mods' / 'shared-v1.jar').read_bytes() == old
    assert (rig.install / 'world/level.dat').read_bytes() == b'world untouched'
    assert (rig.install / 'config/mod.conf').read_text() == 'configuration untouched'
    assert rig.server()['modrinthSync']['instance'] == 'Dinky Adventures'
    assert not (rig.install / sync.MARKER).exists()


def test_repeated_sync_removes_only_previously_managed_absent_or_disabled_mods(rig):
    jar(rig.source, 'one.jar')
    jar(rig.source, 'two.jar')
    jar(rig.mods, 'server-extra.jar')
    rig.apply(rig.preview())
    (rig.source / 'one.jar').unlink()
    (rig.source / 'two.jar').rename(rig.source / 'two.jar.disabled')
    plan = rig.preview()
    assert {r['filename'] for r in plan['changes']} == {'one.jar', 'two.jar'}
    rig.apply(plan)
    assert {p.name for p in rig.mods.iterdir()} == {'server-extra.jar'}


def test_switching_to_a_new_instance_remembers_source_and_preserves_unmanaged(rig):
    jar(rig.source, 'one.jar')
    jar(rig.mods, 'extra.jar')
    rig.apply(rig.preview())
    jar(rig.profiles / 'New Pack/mods', 'two.jar')
    rig.apply(rig.preview('New Pack'))
    assert rig.server()['modrinthSync']['instance'] == 'New Pack'
    assert {p.name for p in rig.mods.iterdir()} == {'two.jar', 'extra.jar'}


@pytest.mark.parametrize('change', ['remove', 'replace'])
def test_local_edits_to_managed_mods_are_conflicts(rig, change):
    jar(rig.source, 'one.jar')
    rig.apply(rig.preview())
    jar(rig.mods, 'one.jar', version='edited')
    if change == 'remove':
        (rig.source / 'one.jar').unlink()
    plan = rig.preview()
    assert plan['conflicts']
    with pytest.raises(sync.SyncError, match='conflicts'):
        rig.apply(plan)


@pytest.mark.parametrize('where', ['source', 'mods'])
def test_stale_preview_detects_changed_files_before_any_writes(rig, where):
    jar(rig.source, 'one.jar')
    plan = rig.preview()
    jar(getattr(rig, where), 'changed.jar')
    with pytest.raises(sync.SyncError, match='files changed'):
        rig.apply(plan)
    assert not (rig.install / 'mod-sync-backups').exists()


@pytest.mark.parametrize('status', ['running', 'starting', 'stopping', 'installing'])
def test_route_rejects_applying_to_active_server(client, rig, status):
    jar(rig.source, 'one.jar')
    plan = client.post('/api/servers/srv_sync/modrinth-sync/preview', json={'instance': 'Dinky Adventures'}).json
    storage.update_server('srv_sync', {'status': status})
    response = client.post('/api/servers/srv_sync/modrinth-sync/apply', json={'planToken': plan['planToken']})
    assert response.status_code == 409
    assert not list(rig.mods.iterdir())


def test_process_running_guard_even_when_saved_status_is_stopped(client, rig):
    plan = rig.preview()
    rig.registry.get_status.return_value = {'status': 'running'}
    response = client.post('/api/servers/srv_sync/modrinth-sync/apply', json={'planToken': plan['planToken']})
    assert response.status_code == 409


def test_api_apply_updates_manifest_and_binds_source(client, rig):
    rig.tag(jar(rig.source, 'known.jar'), ['client_and_server'])
    response = client.post('/api/servers/srv_sync/modrinth-sync/preview', json={'instance': 'Dinky Adventures'})
    assert response.status_code == 200
    response = client.post('/api/servers/srv_sync/modrinth-sync/apply', json={'planToken': response.json['planToken']})
    assert response.status_code == 200 and response.json['synced']
    assert rig.server()['modContent']['known.jar']['pinned'] is True
    assert client.get('/api/servers/srv_sync/modrinth-sync').json['instance'] == 'Dinky Adventures'


@pytest.mark.parametrize('instance', ['../outside', '.', '..', '/tmp', 'Dinky Adventures/../x', 'x\\y', None, ['x']])
def test_path_traversal_and_invalid_instances_rejected(client, rig, instance):
    response = client.post('/api/servers/srv_sync/modrinth-sync/preview', json={'instance': instance})
    assert response.status_code == 400


@pytest.mark.parametrize('location', ['instance', 'mods', 'jar', 'server'])
def test_symlinks_are_not_followed(rig, location):
    other = rig.root / 'elsewhere'
    jar(other, 'hidden.jar')
    if location == 'instance':
        (rig.profiles / 'Link').symlink_to(other, target_is_directory=True)
        with pytest.raises(sync.SyncError):
            rig.preview('Link')
    elif location == 'mods':
        rig.source.rmdir()
        rig.source.symlink_to(other, target_is_directory=True)
        with pytest.raises(sync.SyncError):
            rig.preview()
    else:
        folder = rig.mods if location == 'server' else rig.source
        (folder / 'link.jar').symlink_to(other / 'hidden.jar')
        with pytest.raises(sync.SyncError):
            rig.preview()


def test_expired_and_cross_server_tokens_rejected(rig):
    plan = rig.preview()
    with pytest.raises(sync.SyncError, match='expired'):
        sync.apply({**rig.server(), 'id': 'other'}, rig.install, plan['planToken'], lambda: True)
    sync._plans[plan['planToken']]['expires'] = 0
    with pytest.raises(sync.SyncError, match='expired'):
        rig.apply(plan)


def test_duplicate_and_wrong_minecraft_or_loader_conflicts(rig):
    jar(rig.source, 'one-v1.jar', 'same', version='1')
    jar(rig.source, 'one-v2.jar', 'same', version='2')
    rig.tag(jar(rig.source, 'wrong.jar'), ['client_and_server'], game_versions=['1.20.1'], loaders=['neoforge'])
    plan = rig.preview()
    conflicts = plan['conflicts']
    assert any('Duplicate' in x for x in conflicts)
    assert any('Minecraft 26.3' in x for x in plan['warnings'])
    assert any('does not match fabric' in x for x in conflicts)


def test_changed_server_settings_invalidate_preview(rig):
    plan = rig.preview()
    storage.update_server('srv_sync', {'version': '1.20.1'})
    with pytest.raises(sync.SyncError, match='settings changed'):
        rig.apply(plan)


def test_rollback_if_metadata_write_fails(rig, monkeypatch):
    old = jar(rig.mods, 'old.jar', 'shared', version='1').read_bytes()
    jar(rig.source, 'new.jar', 'shared', version='2')
    plan = rig.preview()
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(storage, 'update_server', fail)
    with pytest.raises(OSError, match='disk full'):
        rig.apply(plan)
    assert {p.name for p in rig.mods.iterdir()} == {'old.jar'}
    assert (rig.mods / 'old.jar').read_bytes() == old
    assert not (rig.install / sync.MARKER).exists()


def test_copy_failure_never_changes_original_mods(rig, monkeypatch):
    jar(rig.source, 'one.jar')
    plan = rig.preview()
    def fail(*args, **kwargs):
        raise OSError('copy failed')
    monkeypatch.setattr(shutil, 'copyfile', fail)
    with pytest.raises(OSError, match='copy failed'):
        rig.apply(plan)
    assert not list(rig.mods.iterdir())
    assert 'modrinthSync' not in rig.server()


def test_interrupted_transaction_blocks_server_start_and_new_sync(rig, monkeypatch):
    (rig.install / sync.MARKER).write_text('{}')
    with pytest.raises(sync.SyncError, match='interrupted'):
        rig.preview()
    registry_module = importlib.import_module('backend.server.registry')
    registry = registry_module.ServerProcessRegistry(rig.root / 'servers')
    monkeypatch.setattr(registry, 'resolve_install_path', lambda server: rig.install)
    result = registry.start_server(rig.server())
    assert result['status'] == 'stopped' and 'interrupted' in result['message']


def test_unconfigured_integration_is_clear(client, rig, monkeypatch):
    monkeypatch.delenv('FABRICATOR_MODRINTH_PROFILES')
    assert client.get('/api/servers/srv_sync/modrinth-sync').json['configured'] is False
    assert client.post('/api/servers/srv_sync/modrinth-sync/preview', json={'instance': 'Dinky Adventures'}).status_code == 409
