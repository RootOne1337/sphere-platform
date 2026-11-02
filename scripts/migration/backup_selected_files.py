#!/usr/bin/env python3
"""Copy selected local trees to a deduplicated, hash-addressed secret store."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from backup_data import protect_directory

ROOT = Path(__file__).resolve().parents[2] / '.local-pilot'
RESERVE = 12 * 1024**3
TREES = ['agent-config', 'updates', 'remote', 'apk', 'motor-ph011-20261023',
         'host-repair-20261006T150602', 'host-repair-20261011T121248Z-ec3fe5cb']
ESSENTIAL_TREES = ['agent-config', 'remote', 'host-repair-20261006T150602',
                   'host-repair-20261011T121248Z-ec3fe5cb']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--profile', choices=['all', 'essential'], default='all')
    args = parser.parse_args()
    dest = args.destination.resolve()
    repository = ROOT.parent
    if dest.is_relative_to(repository) and not dest.is_relative_to((ROOT / 'migration-20261102').resolve()):
        raise SystemExit('Destination must be outside repository or inside migration staging')
    trees = ESSENTIAL_TREES if args.profile == 'essential' else TREES
    latest = []
    if args.profile == 'essential':
        release_file = ROOT / 'updates' / 'releases.json'
        releases = json.loads(release_file.read_text(encoding='utf-8'))
        groups = {}
        for release in releases:
            key = (release['platform'], release['flavor'])
            if key not in groups or release['version_code'] > groups[key]['version_code']:
                groups[key] = release
        for release in groups.values():
            digest = release['sha256']
            if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid release SHA-256')
            path = ROOT / 'updates' / 'artifacts' / (digest + '.apk')
            if not path.is_file():
                raise ValueError(f"Missing latest release artifact for {release['platform']}/{release['flavor']}")
            latest.append(path)
    dest.mkdir(parents=False, exist_ok=False)
    protect_directory(dest)
    blobs = dest / 'blobs'
    blobs.mkdir()
    records = []
    errors = []
    temp = dest / 'copy.partial'
    paths = []
    for tree in trees:
        for base, dirs, files in os.walk(ROOT / tree, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
            for name in files:
                paths.append(Path(base) / name)
    if args.profile == 'essential':
        paths.extend([ROOT / 'updates' / 'releases.json', *latest])
    for source in paths:
                rel = source.relative_to(ROOT).as_posix()
                try:
                    if source.is_symlink():
                        raise ValueError('symlink skipped')
                    before = source.stat()
                    same_drive = os.path.splitdrive(str(dest))[0].lower() == os.path.splitdrive(str(ROOT))[0].lower()
                    reserve = RESERVE if same_drive else 1024**3
                    if shutil.disk_usage(dest).free < reserve + before.st_size:
                        raise ValueError('insufficient free-space reserve')
                    sha = hashlib.sha256()
                    with source.open('rb') as src, temp.open('xb') as out:
                        for chunk in iter(lambda: src.read(1024 * 1024), b''):
                            sha.update(chunk)
                            out.write(chunk)
                    after = source.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise ValueError('source changed while copying')
                    digest = sha.hexdigest()
                    if source in latest and source.stem != digest:
                        raise ValueError('latest APK digest differs from release manifest')
                    target = blobs / digest
                    if target.exists():
                        temp.unlink()
                    else:
                        os.replace(temp, target)
                    records.append({'source': rel, 'sha256': digest, 'bytes': before.st_size, 'mtime_ns': before.st_mtime_ns})
                except (OSError, ValueError) as exc:
                    temp.unlink(missing_ok=True)
                    errors.append({'source': rel, 'error': str(exc)})
    manifest = {'version': 1, 'profile': args.profile, 'trees': trees, 'files': records, 'errors': errors,
                'latest_release_count': len(latest),
                'note': 'essential profile omits older APK artifacts even if releases.json references them'}
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"Copied {len(records)} paths in {len(trees)} trees, latest APKs: {len(latest)}, errors: {len(errors)}.")
    if errors:
        raise SystemExit('Backup incomplete; see private manifest for errors')


if __name__ == '__main__':
    main()
