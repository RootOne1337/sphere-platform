#!/usr/bin/env python3
"""Restore verified reconstruction SQLite backups into a new private directory."""
import hashlib
import json
import shutil
import sys
from pathlib import Path, PurePosixPath

from backup_data import protect_directory


def main():
    store, dest = (Path(x).resolve() for x in sys.argv[1:3])
    entries = json.loads((store / 'manifest.json').read_text(encoding='utf-8'))['entries']
    for item in entries:
        rel = PurePosixPath(item['source'])
        if rel.is_absolute() or '..' in rel.parts or ':' in item['source'] or not item.get('backup'):
            raise ValueError('Unsafe or incomplete SQLite entry')
        name = item['backup']
        if Path(name).name != name:
            raise ValueError('Unsafe SQLite backup name')
        sha = hashlib.sha256()
        with (store / name).open('rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                sha.update(block)
        if sha.hexdigest() != item['sha256'] or (store / name).stat().st_size != item['bytes']:
            raise ValueError('SQLite backup hash mismatch')
    dest.mkdir(parents=False, exist_ok=False)
    protect_directory(dest)
    try:
        for item in entries:
            target = dest.joinpath(*PurePosixPath(item['source']).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with (store / item['backup']).open('rb') as src, target.open('xb') as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
    except Exception:
        print('Restore incomplete; destination retained for inspection.')
        raise
    print(f'Restored {len(entries)} SQLite backups under {dest}.')


if __name__ == '__main__':
    main()
