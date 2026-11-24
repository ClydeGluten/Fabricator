#!/usr/bin/env python3
"""Prepare a host-owned data directory and an isolated Compose configuration.

Does not start/stop containers or copy existing worlds. Run without sudo.
"""
import argparse
import os
from pathlib import Path


def prepare(data_dir: Path, env_file: Path, panel_port=5001, game_port=25566):
    if os.getuid() == 0:
        raise ValueError("Run as your desktop user, without sudo.")
    if env_file.exists():
        raise ValueError(f"{env_file.name} already exists; edit it to change the configuration.")
    data_dir = data_dir.expanduser().resolve()
    if any(c in str(data_dir) for c in "\n\r\x00"):
        raise ValueError("The data directory must not contain control characters.")
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if data_dir.stat().st_uid != os.getuid() or not os.access(data_dir, os.W_OK | os.X_OK):
        raise ValueError("Choose a writable directory owned by your desktop user.")
    values = {
        "FABRICATOR_DATA_DIR": str(data_dir),
        "FABRICATOR_UID": os.getuid(),
        "FABRICATOR_GID": os.getgid(),
        "FABRICATOR_PANEL_PORT": panel_port,
        "FABRICATOR_GAME_PORT": game_port,
        "FABRICATOR_GAME_BIND": "127.0.0.1",
    }
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write("# Local configuration. Never commit this file or the data directory.\n")
        for key, value in values.items():
            escaped = str(value).replace("'", "\\'")
            out.write(f"{key}='{escaped}'\n")
    return data_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", type=Path, nargs="?", default=Path.home() / "Games/Fabricator-data")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        data_dir = prepare(args.data_dir, root / ".env.home")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Data: {data_dir}\nPanel: http://127.0.0.1:5001\nGame preview: 127.0.0.1:25566")
    print("Ready. Start with: ./tools/home-compose.sh up -d --build")


if __name__ == "__main__":
    main()
