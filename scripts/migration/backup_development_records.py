#!/usr/bin/env python3
"""Preserve recent pilot top-level receipts and selected deployment logs, with explicit caps."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from backup_data import ROOT, protect_directory

PILOT = ROOT / '.local-pilot'
DIRS = ('route-service-watchdog', 'reboot-recovery-20261007', 'review-docker-20261002-993d9ea',
        'vehicle-route-deployment-20261102-v1')
PRUNED = {'context', 'node_modules', '.git', '__pycache__', 'venv', '.venv', 'artifacts'}
EXTENSIONS = {'.txt', '.log', '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.ps1', '.py', '.md', '.csv', '.xml'}
PER_FILE = 8 * 1024**2
CAP = 200 * 1024**2


def main():
    dest = Path(sys.argv[1]).resolve()
    if dest.is_relative_to(ROOT) and not dest.is_relative_to((PILOT / 'migration-20261102').resolve()):
        raise ValueError('Destination must be outside repository or inside migration staging')
    candidates = []
    for path in PILOT.iterdir():
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            candidates.append(path)
    missing = []
    for name in DIRS:
        directory = PILOT / name
        if not directory.is_dir():
            missing.append(name)
            continue
        for base, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = [d for d in dirs if d not in PRUNED and not (Path(base) / d).is_symlink()]
            candidates.extend(Path(base) / name for name in files if Path(name).suffix.lower() in EXTENSIONS)
    candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    dest.mkdir(parents=False, exist_ok=False)
    protect_directory(dest)
    (dest / 'blobs').mkdir()
    files, errors, excluded = [], [], []
    selected_bytes = 0
    temp = dest / 'copy.partial'
    for source in candidates:
        rel = source.relative_to(PILOT).as_posix()
        try:
            if source.is_symlink():
                raise ValueError('symlink skipped')
            before = source.stat()
            if before.st_size > PER_FILE or selected_bytes + before.st_size > CAP:
                excluded.append({'source': rel, 'bytes': before.st_size, 'reason': 'file or total size cap'})
                continue
            same = os.path.splitdrive(str(dest))[0].lower() == os.path.splitdrive(str(ROOT))[0].lower()
            reserve = (12 if same else 1) * 1024**3
            if shutil.disk_usage(dest).free < reserve + before.st_size:
                raise ValueError('insufficient free-space reserve')
            digest = hashlib.sha256()
            with source.open('rb') as src, temp.open('xb') as out:
                for chunk in iter(lambda: src.read(1024 * 1024), b''):
                    digest.update(chunk)
                    out.write(chunk)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('source changed while copying')
            sha = digest.hexdigest()
            target = dest / 'blobs' / sha
            if target.exists():
                temp.unlink()
            else:
                os.replace(temp, target)
            selected_bytes += before.st_size
            files.append({'source': rel, 'sha256': sha, 'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns})
        except (OSError, ValueError) as e:
            temp.unlink(missing_ok=True)
            errors.append({'source': rel, 'error': str(e)})
    manifest = {'version': 1, 'profile': 'recent top-level text and selected deployment records',
                'included_directories': list(DIRS), 'pruned_subdirectories': sorted(PRUNED),
                'missing_directories': missing, 'per_file_limit': PER_FILE, 'total_limit': CAP,
                'files': files, 'excluded': excluded, 'errors': errors}
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Copied {len(files)} files ({selected_bytes} bytes); excluded {len(excluded)}; errors {len(errors)}.')
    if errors:
        raise SystemExit('Capture incomplete; see private manifest for errors')


if __name__ == '__main__':
    main()
