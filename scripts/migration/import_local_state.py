#!/usr/bin/env python3
"""Plan or safely merge verified route backups into an existing checkout."""
import argparse
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def safe_path(root, value):
    p = PurePosixPath(value)
    if (not p.parts or p.is_absolute() or '..' in p.parts or '\\' in value or ':' in value
            or any(part.endswith((' ', '.')) for part in p.parts)):
        raise ValueError('Unsafe relative path')
    current = root
    if current.is_symlink():
        raise ValueError('Symlink destination or source root')
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symlink in source or destination path')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('Path escapes its root')
    return current


def collect(recovery, include_private):
    result = {}

    def add(relative, source, expected, size, mtime=None):
        if len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError('Invalid SHA-256')
        if not source.is_file() or source.stat().st_size != size or sha256(source) != expected:
            raise ValueError(f'Backup hash/size mismatch: {relative}')
        existing = result.get(relative)
        if existing and existing['sha256'] != expected:
            raise ValueError(f'Conflicting backup sources: {relative}')
        result[relative] = {'source': source, 'sha256': expected, 'mtime_ns': mtime}

    for dirname in ['routes-essential'] + (['private-config'] if include_private else []):
        folder = recovery / dirname
        doc = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        if doc.get('errors'):
            raise ValueError(f'Incomplete backup: {dirname}')
        for row in doc['files']:
            rel = row['source']
            if dirname == 'routes-essential' and not rel.startswith('reconstruction-jobs/'):
                raise ValueError('Unexpected route path')
            add(rel, safe_path(folder, 'blobs/' + row['sha256']), row['sha256'], row['bytes'], row.get('mtime_ns'))
    folder = recovery / 'routes-sqlite'
    doc = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    for row in doc['entries']:
        if row.get('error') or not row.get('backup'):
            raise ValueError('Incomplete SQLite backup')
        if not row['source'].startswith('reconstruction-jobs/'):
            raise ValueError('Unexpected route SQLite path')
        source = safe_path(folder, row['backup'])
        add(row['source'], source, row['sha256'], row['bytes'])
        with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite quick_check failed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recovery', type=Path)
    parser.add_argument('--workspace', type=Path, default=ROOT)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--include-private-config', action='store_true')
    args = parser.parse_args()
    recovery = args.recovery.resolve(strict=True)
    workspace = args.workspace.resolve(strict=True)
    if not workspace.is_dir():
        raise ValueError('Workspace must be an existing directory')
    target_root = workspace / '.local-pilot'
    items = collect(recovery, args.include_private_config)
    todo = []
    skipped = 0
    destinations = set()
    for relative, item in sorted(items.items()):
        target = safe_path(target_root, relative)
        normalized = os.path.normcase(str(target))
        if normalized in destinations:
            raise ValueError('Conflicting destination names')
        destinations.add(normalized)
        if target.exists():
            if not target.is_file() or sha256(target) != item['sha256']:
                raise ValueError(f'Existing destination differs: {relative}')
            skipped += 1
        else:
            todo.append((relative, item))
    print(f"{'Apply' if args.apply else 'Plan'}: {len(todo)} files to copy; {skipped} identical files already exist.")
    if not args.apply:
        return
    with socket.socket() as sock:
        sock.settimeout(1)
        if sock.connect_ex(('127.0.0.1', 3342)) == 0:
            raise ValueError('Route worker port 3342 is occupied; stop it before import')
    for relative, item in todo:
        target = safe_path(target_root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = safe_path(target_root, relative)
        fd, temporary_name = tempfile.mkstemp(prefix='.migration-import-', dir=target.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, 'wb') as out, item['source'].open('rb') as src:
                shutil.copyfileobj(src, out, 1024 * 1024)
            if sha256(temporary) != item['sha256']:
                raise ValueError('Copied file checksum mismatch')
            if item['mtime_ns'] is not None:
                os.utime(temporary, ns=(item['mtime_ns'], item['mtime_ns']))
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    print('Import complete. Start and validate the route worker separately.')


if __name__ == '__main__':
    main()
