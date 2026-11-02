#!/usr/bin/env python3
"""Copy reconstruction job inputs and small metadata into a private blob store."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from backup_data import ROOT, protect_directory

SOURCE = ROOT / '.local-pilot' / 'reconstruction-jobs'
METADATA = {'.json', '.jsonl', '.yaml', '.yml', '.toml', '.txt', '.log', '.csv', '.ini'}


def main():
    dest = Path(sys.argv[1]).resolve()
    if dest.is_relative_to(ROOT) and not dest.is_relative_to((ROOT / '.local-pilot' / 'migration-20261102').resolve()):
        raise ValueError('Destination must be outside the repository or inside migration staging')
    dest.mkdir(parents=False, exist_ok=False)
    protect_directory(dest)
    blobs = dest / 'blobs'
    blobs.mkdir()
    tmp = dest / 'copy.partial'
    records, errors = [], []
    excluded = {'files': 0, 'bytes': 0}
    videos = {'files': 0, 'bytes': 0}
    for base, dirs, files in os.walk(SOURCE, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
        for name in files:
            path = Path(base) / name
            relative = path.relative_to(SOURCE)
            rel = (Path('reconstruction-jobs') / relative).as_posix()
            try:
                if path.is_symlink():
                    raise ValueError('symlink skipped')
                before = path.stat()
                is_input = len(relative.parts) >= 2 and relative.parts[1] == 'input'
                if not is_input and not (path.suffix.lower() in METADATA and before.st_size <= 1024 * 1024):
                    excluded['files'] += 1
                    excluded['bytes'] += before.st_size
                    continue
                reserve = 12 * 1024**3 if os.path.splitdrive(str(dest))[0].lower() == os.path.splitdrive(str(ROOT))[0].lower() else 1024**3
                if shutil.disk_usage(dest).free < reserve + before.st_size:
                    raise ValueError('insufficient free-space reserve')
                sha = hashlib.sha256()
                with path.open('rb') as src, tmp.open('xb') as out:
                    for chunk in iter(lambda: src.read(1024 * 1024), b''):
                        sha.update(chunk)
                        out.write(chunk)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('source changed while copying')
                digest = sha.hexdigest()
                target = blobs / digest
                if target.exists():
                    tmp.unlink()
                else:
                    os.replace(tmp, target)
                records.append({'source': rel, 'sha256': digest, 'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns})
                if is_input and name.lower() == 'video.h264':
                    videos['files'] += 1
                    videos['bytes'] += before.st_size
            except (OSError, ValueError) as e:
                tmp.unlink(missing_ok=True)
                errors.append({'source': rel, 'error': str(e)})
    manifest = {'version': 1, 'profile': 'reconstruction inputs and small metadata', 'files': records,
                'errors': errors, 'input_video': videos, 'excluded_other_files': excluded}
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Copied {len(records)} paths; video.h264 {videos['files']} ({videos['bytes']} bytes); excluded {excluded['files']} paths ({excluded['bytes']} bytes); errors {len(errors)}.")
    if errors:
        raise SystemExit('Backup incomplete; see private manifest for errors')


if __name__ == '__main__':
    main()
