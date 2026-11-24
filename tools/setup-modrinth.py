#!/usr/bin/env python3
"""Connect a Modrinth profiles folder read-only on the next container recreation."""
import argparse
import os
from pathlib import Path


def configure(profiles: Path, env_file: Path, replace=False):
    profiles = profiles.expanduser().resolve()
    if not profiles.is_dir() or not os.access(profiles, os.R_OK | os.X_OK):
        raise ValueError("Choose the readable Modrinth profiles folder (containing instance directories).")
    if (profiles / 'app.db').exists():
        raise ValueError("Select ModrinthApp/profiles, not the whole app directory containing account data.")
    if any(ord(c) < 32 for c in str(profiles)):
        raise ValueError("The path must not contain control characters.")
    if env_file.exists() and not replace:
        raise ValueError(".env.modrinth already exists. Use --replace to connect a different profiles folder.")
    if env_file.is_symlink():
        raise ValueError("The configuration file must not be a symbolic link.")
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    with os.fdopen(os.open(env_file, flags, 0o600), "w") as stream:
        escaped = str(profiles).replace("'", "\\'")
        stream.write(f"# Local path only. No Modrinth account or token is needed.\nFABRICATOR_MODRINTH_PROFILES_DIR='{escaped}'\n")
    return profiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="?", type=Path, default=Path.home() / ".local/share/ModrinthApp/profiles")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        path = configure(args.profiles, Path(__file__).resolve().parent.parent / ".env.modrinth", args.replace)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Read-only Modrinth profiles: {path}")
    print("Configuration prepared; no containers restarted. When ready: ./tools/home-compose.sh up -d --build")
    print("New instances in this folder appear via Mods → Modrinth instance sync → Refresh list.")


if __name__ == "__main__":
    main()
