#!/usr/bin/env python3
"""Back up reconstruction SQLite files independently with a per-file time limit."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from backup_data import ROOT, protect_directory


def main():
    source = ROOT / '.local-pilot' / 'reconstruction-jobs'
    dest = Path(sys.argv[1]).resolve()
    if not source.is_dir():
        raise ValueError('Reconstruction source does not exist')
    if dest.is_relative_to(ROOT) and not dest.is_relative_to((ROOT / '.local-pilot' / 'migration-20261102').resolve()):
        raise ValueError('Destination must be outside repository or inside migration staging')
    dest.mkdir(parents=False, exist_ok=False)
    protect_directory(dest)
    entries = []
    for path in source.rglob('*'):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in ('.db', '.sqlite', '.sqlite3'):
            continue
        rel = path.relative_to(ROOT / '.local-pilot').as_posix()
        name = hashlib.sha256(rel.encode()).hexdigest() + '.sqlite'
        entry = {'source': rel, 'backup': name}
        entries.append(entry)
        try:
            same_drive = os.path.splitdrive(str(dest))[0].lower() == os.path.splitdrive(str(ROOT))[0].lower()
            reserve = 12 * 1024**3 if same_drive else 1024**3
            if shutil.disk_usage(dest).free < reserve + path.stat().st_size:
                raise ValueError('insufficient reserve')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/migration/backup_sqlite.py'), str(path), str(dest / name)],
                                    capture_output=True, text=True, timeout=30, check=True)
            verified = json.loads(result.stdout)
            with (dest / name).open('rb') as f:
                check = hashlib.file_digest(f, 'sha256').hexdigest()
            if check != verified['sha256'] or (dest / name).stat().st_size != verified['bytes']:
                raise ValueError('SQLite backup readback failed')
            entry.update(verified)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError) as e:
            # Keep incomplete files for inspection and do not mark them as valid backups.
            entry.pop('backup', None)
            entry['error'] = type(e).__name__
        (dest / 'manifest.json').write_text(json.dumps({'version': 1, 'entries': entries}, indent=2), encoding='utf-8')
    print(f"SQLite reconstruction: {sum('sha256' in x for x in entries)} verified backups; {sum('error' in x for x in entries)} failures.")


if __name__ == '__main__':
    main()
