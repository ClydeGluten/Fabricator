#!/usr/bin/env python3
"""Create a new local DuckDNS configuration; never prints the token."""
import getpass
import json
import os
from pathlib import Path
import re

path = Path.home() / ".config/minecraft-ddns/config.json"
if path.exists():
    raise SystemExit(f"Configuration already exists: {path}. Keeping it unchanged.")
domain = input("DuckDNS subdomain (without .duckdns.org): ").strip().lower()
interface = input("Physical network interface (for example enp6s0): ").strip()
token = getpass.getpass("DuckDNS token (hidden): ").strip()
if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", domain):
    raise SystemExit("Invalid subdomain.")
if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", interface):
    raise SystemExit("Invalid network interface.")
if not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", token):
    raise SystemExit("Invalid token format.")
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as out:
    json.dump({"domain": domain, "interface": interface, "token": token}, out)
    out.write("\n")
print(f"Saved {path} with mode 0600. No DNS request has been sent yet.")
