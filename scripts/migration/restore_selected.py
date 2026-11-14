#!/usr/bin/env python3
"""Restore a selected-local blob store into a new private directory."""
import json
import os
import shutil
import sys
from pathlib import Path, PurePosixPath

from backup_data import protect_directory
from backup_verify_selected import main as verify


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: python restore_selected.py SELECTED_STORE NEW_DESTINATION')
    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        relative = PurePosixPath(item['source'])
        if relative.is_absolute() or '..' in relative.parts or not relative.parts or ':' in item['source']:
            raise ValueError('Unsafe source path in manifest')
    verify()
    destination.mkdir(parents=False, exist_ok=False)
    protect_directory(destination)
    try:
        for item in manifest['files']:
            target = destination.joinpath(*PurePosixPath(item['source']).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with (source / 'blobs' / item['sha256']).open('rb') as src, target.open('xb') as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            os.utime(target, ns=(item['mtime_ns'], item['mtime_ns']))
    except Exception:
        print('Restore incomplete; destination retained for inspection.')
        raise
    print(f"Restored {len(manifest['files'])} files under {destination}.")


if __name__ == '__main__':
    main()
