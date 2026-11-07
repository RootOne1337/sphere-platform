#!/usr/bin/env python3
"""Back up one SQLite database with the SQLite backup API in a separate process."""
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import quote


def main():
    source, dest = (Path(x).resolve() for x in sys.argv[1:3])
    if dest.exists():
        raise ValueError('Destination already exists')
    uri = 'file:' + quote(str(source).replace('\\', '/'), safe='/:') + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True, timeout=3)) as src:
        with closing(sqlite3.connect(dest)) as dst:
            src.backup(dst, pages=1024, sleep=0.1)
            if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite quick_check failed')
    sha = hashlib.sha256()
    with dest.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            sha.update(chunk)
    print(json.dumps({'sha256': sha.hexdigest(), 'bytes': dest.stat().st_size, 'quick_check': 'ok'}))


if __name__ == '__main__':
    main()
