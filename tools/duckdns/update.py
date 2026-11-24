#!/usr/bin/env python3
"""Update the Minecraft DuckDNS record through the physical network interface."""
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

CONFIG = Path.home() / ".config/minecraft-ddns/config.json"

def fetch(url, interface):
    # Pass the URL on stdin so the DuckDNS token never appears in process arguments.
    result = subprocess.run(
        ["/usr/bin/curl", "-q", "--ipv4", "--fail", "--silent", "--show-error",
         "--connect-timeout", "5", "--max-time", "20", "--proto", "=https",
         "--noproxy", "*", "--interface", "if!" + interface, "--config", "-"],
        input="url = " + json.dumps(url) + "\n", text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25,
    )
    if result.returncode:
        raise RuntimeError("HTTPS request failed (curl exit " + str(result.returncode) + ")")
    return result.stdout.strip()

def main():
    config = json.loads(CONFIG.read_text())
    domain, token, interface = (config[k] for k in ("domain", "token", "interface"))
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", domain):
        raise RuntimeError("Invalid DuckDNS domain")
    if not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", token):
        raise RuntimeError("Invalid DuckDNS token format")
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", interface):
        raise RuntimeError("Invalid network interface")
    public_ip = None
    for endpoint in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            candidate = ipaddress.IPv4Address(fetch(endpoint, interface))
            if candidate.is_global:
                public_ip = str(candidate)
                break
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            continue
    if public_ip is None:
        raise RuntimeError("Could not obtain a public IPv4 through " + interface)
    url = "https://www.duckdns.org/update?" + urlencode({
        "domains": domain, "token": token, "ip": public_ip, "verbose": "true"
    })
    response = fetch(url, interface).splitlines()
    if len(response) < 2 or response[0] != "OK" or response[1] != public_ip:
        raise RuntimeError("DuckDNS rejected the update or returned a different IPv4")
    print(domain + ".duckdns.org -> " + public_ip + " (DuckDNS OK)")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not log request URLs or token-bearing objects.
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print("Minecraft DDNS update failed: " + message, file=sys.stderr)
        sys.exit(1)
