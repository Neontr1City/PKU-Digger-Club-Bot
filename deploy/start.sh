#!/usr/bin/env bash
# Run as root from an uploaded release. Creates private config only on first start.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$#" -ne 1 ]; then
  echo 'Usage: sudo bash deploy/start.sh https://your-hostname' >&2
  exit 1
fi
python3 - "$1" <<'PY'
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

url = urlsplit(sys.argv[1])
if (url.scheme != 'https' or not url.hostname or url.username or url.password
        or url.path not in ('', '/') or url.query or url.fragment or url.port):
    raise SystemExit('Provide an HTTPS hostname without credentials, path or port.')
base = 'https://' + url.hostname
path = Path('.env.local')
if not path.exists():
    with path.open('x') as file:
        os.chmod(path, 0o600)
        file.write(f'SECRET_KEY={secrets.token_hex(32)}\n'
                   f'ADMIN_PASSWORD={secrets.token_urlsafe(24)}\n'
                   f'PUBLIC_BASE_URL={base}\nDATABASE=/app/data/cricket.sqlite3\n'
                   'OUTPUT_DIR=/app/output\nDEMO_MODE=0\n')
else:
    values = dict(line.split('=', 1) for line in path.read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    if values.get('PUBLIC_BASE_URL') != base or values.get('DEMO_MODE') != '0':
        raise SystemExit('Existing configuration differs; review .env.local before deploying.')
for directory in ('data', 'output'):
    Path(directory).mkdir(exist_ok=True, mode=0o750)
PY
docker compose --env-file .env.local -f deploy/compose.yaml --profile schedule --profile https up -d --build
install -m 0644 deploy/pku-digger-backup.service deploy/pku-digger-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pku-digger-backup.timer
