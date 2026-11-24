# Home-server fork

Owner: ClydeGluten. Base: philderks/Fabricator c6c42dc (v1.8.0).

## Requirements and acceptance checks

1. An isolated Compose project builds this fork, binds a user-selected host
   directory to `/data`, and runs with the host user's UID/GID. Preview defaults
   to panel 5001 and game 25566, without access to the original named volume.
   Files created by the container can be changed from the host and vice versa.
2. Clicking a player's name opens a detail card: coordinates/dimension,
   health, hunger, experience, game mode, inventory, equipment and ender chest.
   Read current NBT through the server console for online players; otherwise
   show the last saved player NBT with its timestamp. Never label a saved
   snapshot as live. Support classic and 26.1+ world layouts and NBT fields.
3. Online actions: heal, feed, clear effects, change game mode, teleport to
   coordinates/dimension or another online player. Reject command injection,
   invalid coordinates, offline targets and requests without panel access.
   Inventory is a viewer, not a destructive inventory editor.
4. Whitelist: searchable entries, add several names at once, remove with undo,
   explicit per-name errors, persistent enable/disable on running or stopped
   servers. Keep `white-list` separate from `enforce-whitelist`.
5. Document clean installation, stopped-server migration with rollback, and
   public IPv4/port-forwarding/DuckDNS setup. No existing container changes,
   game commands, world migration, firewall changes, or DNS changes in this task.

## Implementation / verification sequence

- Storage configuration and setup tool; verify isolation and file ownership.
- Read-only player snapshots and validated console actions; backend tests.
- Player card and whitelist editor; frontend tests, production build and
  browser checks against a disposable panel/server fixture.
- Full backend regression suite, Docker build/smoke check, documentation,
  fork branch/PR and CI. Keep upstream license and attribution.

## Cost

Runs on the user's existing PC. No paid hosting or external AI calls are
required. Expected and peak incremental service subscriptions: $0/month;
electricity and existing Internet service remain the user's normal costs.
