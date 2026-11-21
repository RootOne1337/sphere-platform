"""Bound the project's reviewed image caches; never prune Docker globally.

Only exact marked ZIP/TAR copies and unreferenced images from our two CI image
namespaces are eligible. Containers, volumes, build caches and source stay intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.local_ci import execution_lock

NAMES = ('sphere-review-frontend', 'sphere-reviewed-backend')
SHA = re.compile(r'[a-f0-9]{40}\Z')
ID = re.compile(r'sha256:[a-f0-9]{64}\Z')
OWNED = re.compile(r'(?:ci-[a-f0-9]{7,40}-(?:backend|web)|reviewed-(?:(?:mdns-)?backend|(?:mdns-)?web)-[a-f0-9]{7,40}(?:-[a-z0-9-]+)?)\Z')


def command(root: Path, args: list[str]) -> str:
    result = subprocess.run(args, cwd=root, capture_output=True, text=True,
                            encoding='utf-8', errors='strict', timeout=60)
    if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
        raise ValueError('metadata_command_failed_or_budget')
    return result.stdout.strip()


def regular(path: Path, base: Path) -> Path:
    resolved = path.resolve(strict=True)
    if (not resolved.is_relative_to(base.resolve(strict=True)) or not path.is_file()
            or path.is_symlink() or (os.name == 'nt' and path.is_junction())
            or any(p.is_symlink() or os.name == 'nt' and p.is_junction()
                   for p in path.parents if p != base.parent)):
        raise ValueError('cache_path_redirected_or_not_regular')
    return resolved


def bounded_json(path: Path, base: Path) -> dict:
    regular(path, base)
    if path.stat().st_size > 256 * 1024:
        raise ValueError('receipt_budget')
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('receipt_shape')
    return value


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def archive_identity(directory: Path, receipt: dict, file: str, base: Path) -> dict:
    if file not in {'download.zip', 'image.tar.gz'}:
        raise ValueError('unsupported_cache_file')
    path = regular(directory / file, base)
    expected = receipt.get('archive')
    if file == 'download.zip':
        proof = bounded_json(directory / 'download-proof.json', base)
        if proof.get('githubDigestVerified') is not True or proof.get('sourceRevision') != receipt['sourceRevision']:
            raise ValueError('download_not_verified')
        expected = {'bytes': proof.get('zipBytes'), 'sha256': proof.get('zipSha256')}
    if (not isinstance(expected, dict) or type(expected.get('bytes')) is not int
            or not 0 < expected['bytes'] <= 512 * 1024 * 1024
            or path.stat().st_size != expected['bytes'] or digest(path) != expected.get('sha256')):
        raise ValueError('cache_content_mismatch')
    return {'file': str(path.relative_to(base)), 'bytes': expected['bytes'], 'sha256': expected['sha256']}


def remove_archive(base: Path, item: dict) -> None:
    path = regular(base / item['file'], base)
    if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
        raise ValueError('cache_changed_before_remove')
    path.unlink()  # One bounded regular file; never recurse or remove a directory.


def retained_sources(records: list[dict], keep: int) -> set[str]:
    result = set()
    for kind in NAMES:
        sources = []
        for row in sorted(records, key=lambda r: r['created'], reverse=True):
            if row['kind'] == kind and row['source'] not in sources:
                sources.append(row['source'])
        result.update(sources[:keep])
    return result


def pending_archive_records(base: Path, history: set[str]) -> list[dict]:
    """Downloaded candidates have no Docker image yet. Retain them by component too."""
    records = []
    for directory in base.iterdir():
        if not OWNED.fullmatch(directory.name) or not directory.is_dir() or not (directory / 'receipt.json').exists():
            continue
        try:
            receipt = bounded_json(directory / 'receipt.json', base)
            source = receipt.get('sourceRevision', '')
            tag = receipt.get('image', {}).get('tag')
            created = receipt.get('observedAtUtc', '')
            if (source not in history or receipt.get('repository') != 'RootOne1337/sphere-platform'
                    or type(receipt.get('runId')) is not int or receipt['runId'] <= 0
                    or tag not in [kind + ':' + source for kind in NAMES]
                    or not isinstance(created, str)):
                continue
            datetime.fromisoformat(created.replace('Z', '+00:00'))
            present = next((name for name in ('image.tar.gz', 'download.zip') if (directory / name).exists()), None)
            if present is None:
                continue
            archive_identity(directory, receipt, present, base)
            records.append({'kind': tag.split(':')[0], 'source': source, 'created': created})
        except (ValueError, OSError, KeyError, TypeError):
            continue
    return records


def execute(root: Path, *, apply: bool = False, images: bool = False, keep: int = 3,
            protect_source: str | None = None, protect_images: tuple[str, ...] = ()) -> dict:
    if (not 3 <= keep <= 10 or protect_source is not None and not SHA.fullmatch(protect_source)
            or len(protect_images) > 8 or any(not ID.fullmatch(i) for i in protect_images)):
        raise ValueError('retention_configuration')
    root = root.resolve(strict=True)
    base = root / '.local-pilot'
    if not base.is_dir() or base.is_symlink() or os.name == 'nt' and base.is_junction():
        raise ValueError('private_cache_redirected')
    with execution_lock(base / 'reviewed-retention.lock'):
        history = set(command(root, ['git', 'rev-list', 'HEAD']).splitlines())
        inventory = [json.loads(line) for line in command(root, ['docker', 'image', 'ls', '--no-trunc',
                      '--format', '{{json .}}']).splitlines()]
        tags = sorted({r['Repository'] + ':' + r['Tag'] for r in inventory
                       if r['Repository'] in NAMES and SHA.fullmatch(r['Tag'])})
        data = json.loads(command(root, ['docker', 'image', 'inspect', *tags])) if tags else []
        if len(data) > 256:
            raise ValueError('image_inventory_budget')
        containers = command(root, ['docker', 'ps', '-aq', '--no-trunc']).splitlines()
        if len(containers) > 128:
            raise ValueError('container_inventory_budget')
        used = set(command(root, ['docker', 'inspect', '--format', '{{.Image}}', *containers]).splitlines()) if containers else set()
        records = []
        for image in data:
            labels = image.get('Config', {}).get('Labels') or {}
            source = labels.get('org.opencontainers.image.revision', '')
            aliases = image.get('RepoTags') or []
            if (source not in history or not ID.fullmatch(image.get('Id', ''))
                    or not str(labels.get('io.sphere.ci.run', '')).isdigit()
                    or not str(labels.get('io.sphere.ci.attempt', '')).isdigit()
                    or image.get('Os') != 'linux' or image.get('Architecture') != 'amd64'
                    or not aliases or any(t not in [n + ':' + source for n in NAMES] for t in aliases)):
                continue
            records.append({'id': image['Id'], 'source': source, 'kind': aliases[0].split(':')[0],
                            'tags': aliases, 'created': image['Created'], 'referenced': image['Id'] in used})
        records = list({r['id']: r for r in records}.values())
        protected = retained_sources(records + pending_archive_records(base, history), keep) | ({protect_source} if protect_source else set())
        protected.update(r['source'] for r in records if r['referenced'] or r['id'] in protect_images)
        archive_plan, rejected = [], []
        for directory in base.iterdir():
            if not OWNED.fullmatch(directory.name) or not directory.is_dir():
                continue
            receipt_path = directory / 'receipt.json'
            if not receipt_path.exists():
                continue
            try:
                receipt = bounded_json(receipt_path, base)
                source = receipt.get('sourceRevision', '')
                if (source not in history or receipt.get('repository') != 'RootOne1337/sphere-platform'
                        or type(receipt.get('runId')) is not int or receipt['runId'] <= 0
                        or receipt.get('image', {}).get('tag') not in [n + ':' + source for n in NAMES]):
                    raise ValueError('cache_marker_not_owned')
                if source in protected:
                    continue
                for file in ['image.tar.gz', 'download.zip']:
                    if (directory / file).exists():
                        archive_plan.append(archive_identity(directory, receipt, file, base))
            except (ValueError, OSError, KeyError) as error:
                rejected.append({'directory': directory.name, 'reason': str(error)[:80]})
        result = {'schemaVersion': 1, 'observedAt': datetime.now(timezone.utc).isoformat(),
                  'apply': apply, 'keepSourcesPerComponent': keep, 'protectedSources': sorted(protected),
                  'archivePlan': archive_plan, 'archiveBytes': sum(r['bytes'] for r in archive_plan),
                  'imagePlan': [r for r in records if not r['referenced'] and r['source'] not in protected],
                  'rejectedArchives': rejected, 'removedArchives': [], 'removedImages': [],
                  'dockerGlobalPrune': False, 'volumesTouched': False,
                  'freeHostBytesBefore': shutil.disk_usage(root).free}
        filename = base / ('reviewed-retention-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        write_json(filename, result)
        if apply:
            for item in archive_plan:
                remove_archive(base, item)
                result['removedArchives'].append(item)
                write_json(filename, result)
            if images:
                for item in result['imagePlan']:
                    # Docker's non-force removal atomically refuses new container references.
                    current = json.loads(command(root, ['docker', 'image', 'inspect', item['id']]))[0]
                    if current.get('Id') != item['id'] or current.get('RepoTags') != item['tags']:
                        raise ValueError('image_changed_before_remove')
                    command(root, ['docker', 'image', 'rm', item['id']])
                    result['removedImages'].append(item)
                    write_json(filename, result)
        result['freeHostBytesAfter'] = shutil.disk_usage(root).free
        result['physicalVhdCompactionPerformed'] = False
        write_json(filename, result)
        return result | {'receiptFile': str(filename.relative_to(root))}


def post_install(root: Path, source: str, previous_image: str) -> dict:
    """Cache maintenance must not roll back a healthy delivered runtime.

    Explicitly preserve the previous image even when it was not a recent build.
    A failure is visible, rather than claimed as successful cleanup.
    """
    try:
        result = execute(root, apply=True, images=True, protect_source=source,
                         protect_images=(previous_image,))
        return {'state': 'completed', 'receiptFile': result['receiptFile'],
                'archivesRemoved': len(result['removedArchives']), 'imagesRemoved': len(result['removedImages'])}
    except Exception as error:
        return {'state': 'not-completed', 'cleanupClaimed': False, 'errorType': type(error).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--images', action='store_true')
    parser.add_argument('--protect-source')
    args = parser.parse_args()
    result = execute(Path(__file__).resolve().parents[2], apply=args.apply, images=args.images,
                     protect_source=args.protect_source)
    print(json.dumps({k: result[k] for k in ['apply', 'archiveBytes', 'freeHostBytesBefore',
                     'freeHostBytesAfter', 'physicalVhdCompactionPerformed', 'receiptFile']} |
                     {'archiveCandidates': len(result['archivePlan']), 'imageCandidates': len(result['imagePlan']),
                      'archivesRemoved': len(result['removedArchives']), 'imagesRemoved': len(result['removedImages']),
                      'rejectedArchives': result['rejectedArchives']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
