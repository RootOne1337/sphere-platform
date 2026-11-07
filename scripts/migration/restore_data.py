#!/usr/bin/env python3
"""Restore selected snapshot components into NEW Docker volumes only."""
import argparse
import hashlib
import json
import os
import posixpath
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, **kwargs)


def inspect_safe_archive(path):
    with tarfile.open(path, 'r:gz') as archive:
        for item in archive:
            name = PurePosixPath(item.name)
            if name.is_absolute() or '..' in name.parts or item.isdev() or item.isfifo():
                raise ValueError('Unsafe archive member')
            if item.issym() or item.islnk():
                link = item.linkname
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(item.name), link))
                if link.startswith('/') or resolved == '..' or resolved.startswith('../'):
                    raise ValueError('Unsafe archive link')
            if item.isfile():
                f = archive.extractfile(item)
                while f.read(1024 * 1024):
                    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--project', required=True, help='new isolated target prefix, e.g. migration-test-20261102')
    parser.add_argument('--database', choices=['sphereplatform', 'n8n', 'postgres'], action='append', default=[])
    parser.add_argument('--pg-password-file', type=Path, help='existing private UTF-8 password file for the new PostgreSQL superuser')
    parser.add_argument('--volume', action='append', default=[], help='volume suffix from manifest, e.g. minio_data')
    parser.add_argument('--compose-volumes', action='store_true', help='use Compose project_volume naming')
    parser.add_argument('--preserve-roles', action='store_true', help='restore globals, database owners and privileges into isolated PostgreSQL')
    args = parser.parse_args()
    if not args.project.startswith('migration-') or not all(c.islower() or c.isdigit() or c == '-' for c in args.project):
        parser.error('project must start migration- and contain only lowercase letters, digits and hyphens')
    if not args.database and not args.volume:
        parser.error('select at least one --database or --volume')
    if args.database and not args.pg_password_file:
        parser.error('--pg-password-file is required when restoring databases')
    if args.preserve_roles and (not args.database or 'postgres' in args.database):
        parser.error('--preserve-roles requires application databases and excludes the postgres maintenance database')
    password = args.pg_password_file.read_text(encoding='utf-8').rstrip('\r\n') if args.database else None
    if args.database and not password:
        parser.error('PostgreSQL password file is empty')
    folder = args.snapshot.resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    selected = []
    for db in sorted(set(args.database)):
        selected.append((f'postgres-{db}.dump', 'postgres-custom'))
    if args.preserve_roles:
        selected.append(('postgres-globals.sql', 'postgres-globals'))
    for vol in sorted(set(args.volume)):
        if not vol or not all(c.islower() or c.isdigit() or c in '_-' for c in vol):
            parser.error('invalid volume suffix')
        selected.append((f'volume-{vol}.tar.gz', 'docker-volume'))
    entries = {x['path']: x for x in manifest['artifacts']}
    for name, kind in selected:
        item = entries.get(name)
        if not item or item['kind'] != kind:
            raise ValueError(f'Missing selected artifact: {name}')
        path = folder / name
        h = hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                h.update(block)
        if h.hexdigest() != item['sha256'] or path.stat().st_size != item['size']:
            raise ValueError(f'Hash/size mismatch: {name}')
        if kind == 'docker-volume':
            inspect_safe_archive(path)
    def volname(suffix):
        return args.project + '_' + suffix if args.compose_volumes else args.project + '-' + suffix.replace('_', '-')

    pgvol = volname('postgres_data') if args.compose_volumes else args.project + '-postgres'
    names = [volname(v) for v in sorted(set(args.volume))]
    if args.database:
        names.append(pgvol)
    if len(names) != len(set(names)):
        raise ValueError('Selected volume names collide')
    for name in names:
        if subprocess.run(['docker', 'volume', 'inspect', name], capture_output=True).returncode == 0:
            raise ValueError(f'Target volume already exists: {name}')
    for image in (['alpine:latest'] if args.volume else []) + (['postgres:15-alpine'] if args.database else []):
        docker('image', 'inspect', image, capture_output=True)
    cid = None
    try:
        for name in names:
            if args.compose_volumes:
                suffix = name.removeprefix(args.project + '_')
                docker('volume', 'create', '--label', f'com.docker.compose.project={args.project}',
                       '--label', f'com.docker.compose.volume={suffix}', name, capture_output=True)
            else:
                docker('volume', 'create', name, capture_output=True)
        for vol in sorted(set(args.volume)):
            target = volname(vol)
            with (folder / f'volume-{vol}.tar.gz').open('rb') as f:
                docker('run', '--rm', '-i', '--network', 'none', '--mount', f'type=volume,src={target},dst=/data',
                       'alpine:latest', 'tar', 'xzf', '-', '-C', '/data', stdin=f, capture_output=True)
            print(f'Restored volume {target}.', flush=True)
        if args.database:
            local_env = os.environ.copy()
            local_env['POSTGRES_PASSWORD'] = password
            cid = docker('run', '-d', '--network', 'none', '-e', 'POSTGRES_PASSWORD', '--mount',
                f'type=volume,src={pgvol},dst=/var/lib/postgresql/data',
                         'postgres:15-alpine', env=local_env, capture_output=True, text=True).stdout.strip()
            for _ in range(60):
                if subprocess.run(['docker', 'exec', cid, 'pg_isready', '-U', 'postgres'], capture_output=True).returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('PostgreSQL restore container did not start')
            if args.preserve_roles:
                with (folder / 'postgres-globals.sql').open('rb') as f:
                    docker('exec', '-i', cid, 'psql', '-U', 'postgres', '-d', 'postgres', '-v',
                           'ON_ERROR_STOP=1', stdin=f, capture_output=True)
            for db in sorted(set(args.database)):
                if not args.preserve_roles and db != 'postgres':
                    docker('exec', cid, 'createdb', '-U', 'postgres', db, capture_output=True)
                with (folder / f'postgres-{db}.dump').open('rb') as f:
                    options = ['-C', '-d', 'postgres'] if args.preserve_roles else ['-d', db, '--no-owner', '--no-privileges']
                    docker('exec', '-i', cid, 'pg_restore', '-U', 'postgres', '--exit-on-error',
                           *options, stdin=f, capture_output=True)
                print(f'Restored database {db} to {pgvol}.', flush=True)
    except Exception:
        print('Restore incomplete; created volumes were retained for inspection and must not be treated as complete.')
        raise
    finally:
        if cid:
            subprocess.run(['docker', 'rm', '-f', '-v', cid], capture_output=True)
    print('Completed. n8n encryption key and application configuration require separate recovery; no ports were published.')


if __name__ == '__main__':
    main()
