#!/usr/bin/env python3
"""Read and verify each unique content-addressed local backup blob."""
import hashlib
import json
import sys
from pathlib import Path


def main():
    folder = Path(sys.argv[1]).resolve()
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    blobs = {item['sha256']: item['bytes'] for item in manifest['files']}
    for digest, size in blobs.items():
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Invalid blob digest in manifest')
        p = folder / 'blobs' / digest
        h = hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
        if h.hexdigest() != digest or p.stat().st_size != size:
            raise ValueError('Blob hash mismatch: ' + digest)
    if manifest['errors']:
        raise ValueError(f"Snapshot contains {len(manifest['errors'])} copy errors")
    print(f"Verified {len(blobs)} blobs covering {len(manifest['files'])} paths.")


if __name__ == '__main__':
    main()
