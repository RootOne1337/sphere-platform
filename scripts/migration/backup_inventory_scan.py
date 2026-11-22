#!/usr/bin/env python3
"""Inventory pilot top-level data and locate SQLite candidates without copying."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / '.local-pilot'


def main():
    out = Path(sys.argv[1]).resolve()
    if not out.is_relative_to((ROOT / 'migration-20261102').resolve()):
        raise SystemExit('Output must be inside migration staging')
    result = {'created_utc': datetime.now(timezone.utc).isoformat(), 'roots': {}, 'sqlite_candidates': [], 'errors': []}
    for base, dirs, files in os.walk(ROOT, followlinks=False):
        base = Path(base)
        if base == ROOT:
            dirs[:] = [d for d in dirs if d != 'migration-20261102']
        dirs[:] = [d for d in dirs if not (base / d).is_symlink()]
        for name in files:
            path = base / name
            rel = path.relative_to(ROOT).as_posix()
            entry = result['roots'].setdefault(rel.split('/')[0], {'files': 0, 'bytes': 0})
            try:
                if path.is_symlink():
                    result['errors'].append({'path': rel, 'error': 'symlink skipped'})
                    continue
                size = path.stat().st_size
                entry['files'] += 1
                entry['bytes'] += size
                if path.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
                    result['sqlite_candidates'].append({'source': rel, 'bytes': size,
                        'backup_filename': hashlib.sha256(rel.encode()).hexdigest() + '.sqlite'})
            except OSError as e:
                result['errors'].append({'path': rel, 'error': str(e)})
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Inventory: {len(result['roots'])} roots, {len(result['sqlite_candidates'])} database candidates, {len(result['errors'])} errors.")


if __name__ == '__main__':
    main()
