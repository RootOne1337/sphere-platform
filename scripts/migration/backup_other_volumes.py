#!/usr/bin/env python3
"""Optionally capture all Docker volumes, including inactive projects and caches."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from .backup_data import ROOT, protect_directory
except ImportError:
    from backup_data import ROOT, protect_directory


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def inventory():
    names = docker('volume', 'ls', '-q', capture_output=True, text=True).stdout.splitlines()
    details = json.loads(docker('system', 'df', '-v', '--format', 'json', capture_output=True, text=True).stdout)
    sizes = {row['Name']: row.get('Size', 'unknown') for row in details.get('Volumes', [])}
    return [(name, sizes.get(name, 'unknown')) for name in names]


def must_exist(name):
    result = subprocess.run(['docker', 'volume', 'inspect', name], capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f'Source volume is missing: {name}')
    records = json.loads(result.stdout)
    if len(records) != 1 or records[0].get('Name') != name or not records[0].get('CreatedAt'):
        raise ValueError(f'Source volume identity unavailable: {name}')
    return {key: records[0].get(key) for key in ('Name', 'CreatedAt', 'Driver', 'Options', 'Labels')}


def ensure_unchanged(name, identity):
    if must_exist(name) != identity:
        raise ValueError(f'Source volume identity changed: {name}')


def capture_volume(name, output, reserve, identity):
    # A deleted source might otherwise be silently re-created by docker run.
    ensure_unchanged(name, identity)
    container = 'migration-volume-copy-' + uuid.uuid4().hex
    partial = output.with_suffix(output.suffix + '.partial')
    sha = hashlib.sha256()
    try:
        with partial.open('xb') as file:
            proc = subprocess.Popen(['docker', 'run', '--rm', '--network', 'none', '--name', container,
                                     '--mount', f'type=volume,src={name},dst=/data,readonly',
                                     'alpine:latest', 'tar', 'czf', '-', '-C', '/data', '.'],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                for block in iter(lambda: proc.stdout.read(1024 * 1024), b''):
                    if shutil.disk_usage(output.parent).free < reserve + len(block):
                        raise ValueError('Destination free-space reserve reached')
                    file.write(block)
                    sha.update(block)
                if proc.wait() != 0:
                    raise ValueError('Volume archive failed or source changed')
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        with tarfile.open(partial, 'r:gz') as archive:
            for member in archive:
                if member.isfile():
                    f = archive.extractfile(member)
                    while f.read(1024 * 1024):
                        pass
        with partial.open('rb') as f:
            if hashlib.file_digest(f, 'sha256').hexdigest() != sha.hexdigest():
                raise ValueError('Volume archive readback hash mismatch')
        ensure_unchanged(name, identity)
        os.replace(partial, output)
        return {'sha256': sha.hexdigest(), 'bytes': output.stat().st_size}
    finally:
        subprocess.run(['docker', 'rm', '-f', container], capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    dest = args.destination.resolve()
    if dest.exists() or not dest.parent.is_dir():
        parser.error('Destination must be new under an existing directory')
    if dest.is_relative_to(ROOT) and not dest.is_relative_to((ROOT / '.local-pilot/migration-20261102').resolve()):
        parser.error('Destination must be outside repository or inside ignored migration staging')
    rows = inventory()
    identities = {name: must_exist(name) for name, _size in rows}
    if args.plan:
        for name, size in rows:
            print(f'{name}\t{size}')
        print(f'{len(rows)} volumes; sizes are Docker estimates; no archive created.')
        return
    same = os.path.splitdrive(str(dest))[0].lower() == os.path.splitdrive(str(ROOT))[0].lower()
    reserve = (12 if same else 1) * 1024**3
    if shutil.disk_usage(dest.parent).free < reserve:
        raise ValueError('Destination free-space reserve reached')
    docker('image', 'inspect', 'alpine:latest', capture_output=True)
    dest.mkdir(parents=False, exist_ok=False)
    protect_directory(dest)
    ids = docker('ps', '-aq', capture_output=True, text=True).stdout.splitlines()
    if ids:
        inspect = docker('inspect', *ids, capture_output=True).stdout
        (dest / 'container-inspect-sensitive.json').write_bytes(inspect)
    metadata = docker('volume', 'inspect', *(name for name, _ in rows), capture_output=True).stdout if rows else b'[]'
    (dest / 'volume-inspect-sensitive.json').write_bytes(metadata)
    artifacts = []
    for name, size in rows:
        filename = hashlib.sha256(name.encode()).hexdigest() + '.tar.gz'
        result = capture_volume(name, dest / filename, reserve, identities[name])
        artifacts.append({'volume': name, 'file': filename, 'docker_size': size, **result,
                          'consistency': 'live filesystem copy, not application-consistent'})
        print(f'Captured {len(artifacts)}/{len(rows)} volumes.', flush=True)
    manifest = {'version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(), 'volumes': artifacts,
                'warnings': ['All current volumes including caches and inactive projects; application consistency is not guaranteed.',
                             'Container inspection and volume metadata contain secrets; images are not included.',
                             'Source identity is checked before and after capture; this is not a transactional snapshot.']}
    for name in ('container-inspect-sensitive.json', 'volume-inspect-sensitive.json'):
        path = dest / name
        if path.exists():
            with path.open('rb') as f:
                digest = hashlib.file_digest(f, 'sha256').hexdigest()
            manifest.setdefault('metadata', []).append({'file': name, 'sha256': digest, 'bytes': path.stat().st_size})
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('All volume archives read back and verified; restore is not yet tested.')


if __name__ == '__main__':
    main()
