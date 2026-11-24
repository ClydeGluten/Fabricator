#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env.home ]; then
    echo 'First run: python3 tools/setup-home.py /your/data/directory' >&2
    exit 1
fi
exec docker compose --project-name fabricator-home --env-file .env.home -f compose.home.yml "$@"
