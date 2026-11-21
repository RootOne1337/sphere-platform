"""Minimal independent files for an isolated localization HTTP replay.

No video, extracted images, COLMAP databases, old model revisions or reports are
copied. They are not used by the live localization API. Files are copied rather
than hard linked so later fixture writes cannot alter the source workspace.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.pilot.atomic_json import write_json

ID = re.compile(r'[0-9a-f]{32}')
SHA = re.compile(r'[0-9a-f]{64}')
TERMINAL = {'complete','sparse_complete','partial_scene','failed','cancelled','quality_rejected','review_required'}


def snapshot(source: Path, destination: Path, key: str) -> dict:
    source, destination = Path(source), Path(destination)
    if (not isinstance(key,str) or not SHA.fullmatch(key) or not source.is_dir()
            or destination.exists() or destination.is_symlink()
            or destination.resolve().is_relative_to(source.resolve())
            or source.resolve().is_relative_to(destination.resolve())):
        raise ValueError('replay_snapshot_scope')
    for path in (source, destination.parent):
        if any(part.is_symlink() for part in (path,*path.parents)):
            raise ValueError('replay_snapshot_symlink')

    def read(name, maximum):
        path=source/name
        if (any(p.is_symlink() for p in (path,*path.parents))
                or not path.is_file() or not 0<path.stat().st_size<=maximum):
            raise ValueError('replay_snapshot_asset')
        raw=path.read_bytes()
        if len(raw)>maximum:
            raise ValueError('replay_snapshot_asset')
        return raw

    active=read('navigation/active.json',65536)
    identity=json.loads(active).get('id')
    if not isinstance(identity,str) or not ID.fullmatch(identity):
        raise ValueError('replay_snapshot_navigation')
    nav=f'navigation/{identity}'
    limits={'control.json':65536,'state.json':65536,'geometry.json':16*1024**2,
            'input/manifest.json':65536,'navigation/active.json':65536,
            f'{nav}/state.json':65536,f'{nav}/receipt.json':65536,f'{nav}/route.json':4*1024**2}
    if (source/'quality.json').exists():
        limits['quality.json']=65536
    files={name:read(name,limit) for name,limit in limits.items()}
    if (json.loads(files['state.json']).get('phase') not in TERMINAL
            or json.loads(files[f'{nav}/state.json']).get('phase')!='ready'
            or files['navigation/active.json']!=active):
        raise ValueError('replay_snapshot_requires_ready')
    hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    receipt=json.loads(files[f'{nav}/receipt.json'])
    if (receipt.get('sha256')!=hashes[f'{nav}/route.json']
            or receipt.get('geometry_sha256')!=hashes['geometry.json']
            or receipt.get('source_capture_sha256')!=hashes['input/manifest.json']):
        raise ValueError('replay_snapshot_binding')
    if any(read(name,limits[name])!=raw for name,raw in files.items()):
        raise ValueError('replay_snapshot_source_changed')
    destination.mkdir(parents=True)
    control=json.loads(files['control.json']);control['key_sha256']=hashlib.sha256(key.encode()).hexdigest()
    copied_hashes={}
    for name,raw in files.items():
        if name=='control.json':
            raw=json.dumps(control).encode()
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as output: output.write(raw)
        copied_hashes[name]=hashlib.sha256(raw).hexdigest()
    result=dict(schema='sphere-replay-snapshot-v1',source=str(source.resolve()),
                sourceHashes=hashes,copiedBytes=sum(len(x) for x in files.values()),
                files=len(files),copiedHashes=copied_hashes,physicalActions=0,copiedVideo=False,copiedDatabases=False)
    write_json(destination/'replay-snapshot.json',result)
    return result


def discard_snapshot(destination: Path, receipt: Path) -> None:
    """After its HTTP server is closed, retain hashes and remove owned copies.

    Refuse unexpected files or a changed fixture. Never recurse through links
    or remove a source folder. A failed cleanup remains visible for inspection.
    """
    destination,receipt=Path(destination),Path(receipt)
    marker=destination/'replay-snapshot.json'
    if (not marker.is_file() or marker.is_symlink() or marker.stat().st_size>65536
            or receipt.exists() or receipt.is_symlink()
            or receipt.resolve().is_relative_to(destination.resolve())
            or any(p.is_symlink() for p in (destination,*destination.parents,receipt.parent,*receipt.parent.parents))):
        raise ValueError('replay_snapshot_cleanup_scope')
    data=json.loads(marker.read_bytes()); hashes=data.get('copiedHashes')
    if (data.get('schema')!='sphere-replay-snapshot-v1' or data.get('physicalActions')!=0
            or not isinstance(hashes,dict) or not 8<=len(hashes)<=9
            or Path(data['source']).resolve()==destination.resolve()
            or Path(data['source']).resolve().is_relative_to(destination.resolve())
            or destination.resolve().is_relative_to(Path(data['source']).resolve())):
        raise ValueError('replay_snapshot_cleanup_scope')
    paths=[];directories=[]
    for path in destination.rglob('*'):
        if path.is_symlink() or not path.resolve().is_relative_to(destination.resolve()):
            raise ValueError('replay_snapshot_cleanup_scope')
        if path.is_dir(): directories.append(path);continue
        name=path.relative_to(destination).as_posix()
        if path==marker: continue
        if name not in hashes or hashlib.sha256(path.read_bytes()).hexdigest()!=hashes[name]:
            raise ValueError('replay_snapshot_cleanup_changed')
        paths.append(path)
    if len(paths)!=len(hashes):
        raise ValueError('replay_snapshot_cleanup_changed')
    write_json(receipt,dict(data,temporaryCopiesRemoved=True))
    # No recursive deletion; the exact finite set was validated above.
    for path in paths: path.unlink()
    marker.unlink()
    for directory in sorted(directories,key=lambda p:len(p.parts),reverse=True): directory.rmdir()
    destination.rmdir()
