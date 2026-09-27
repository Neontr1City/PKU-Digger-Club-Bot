"""Package the current source, including uncommitted code, without private data."""

import argparse
import base64
import hashlib
import json
import shlex
import subprocess
import tarfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', help='Also prepare an Azure Run Command upload script.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = root / 'output' / 'deploy'
    output.mkdir(parents=True, exist_ok=True)
    paths = (
        subprocess.check_output(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root
        )
        .decode()
        .split('\0')
    )
    selected = sorted(
        name
        for name in paths
        if name
        and (
            name.startswith(('cricket/', 'deploy/'))
            or name in ('Dockerfile', '.dockerignore', 'requirements.txt')
        )
    )
    manifest = {}
    archive = output / 'release.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for name in selected:
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Unexpected source file: {name}')
            manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            bundle.add(path, arcname=name, recursive=False)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if args.base_url:
        contents = base64.b64encode(archive.read_bytes()).decode()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (output / 'upload-release.sh').write_text(
            'set -eu\n'
            'install -d -m 0750 /opt/pku-digger-club-bot\n'
            "base64 -d >/var/tmp/pku-digger-release.tar.gz <<'PKU_RELEASE_ARCHIVE'\n"
            + contents
            + '\nPKU_RELEASE_ARCHIVE\n'
            + f"echo '{digest}  /var/tmp/pku-digger-release.tar.gz' | sha256sum -c -\n"
            + 'tar --no-same-owner -xzf /var/tmp/pku-digger-release.tar.gz '
            '-C /opt/pku-digger-club-bot\n'
            'cd /opt/pku-digger-club-bot\n'
            f'bash deploy/start.sh {shlex.quote(args.base_url)}\n'
            'echo DEPLOY_OK\n'
        )
    print(f'{archive}: {len(selected)} source files; SHA-256 manifest saved alongside it.')


if __name__ == '__main__':
    main()
