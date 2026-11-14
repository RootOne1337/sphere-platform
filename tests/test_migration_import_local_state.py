import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.migration import import_local_state as module


@pytest.fixture
def fixture(tmp_path):
    recovery = tmp_path / 'backup'
    route = recovery / 'routes-essential'
    (route / 'blobs').mkdir(parents=True)
    data = b'route input'
    sha = hashlib.sha256(data).hexdigest()
    (route / 'blobs' / sha).write_bytes(data)
    row = {'source': 'reconstruction-jobs/job/input/video.h264', 'sha256': sha, 'bytes': len(data)}
    (route / 'manifest.json').write_text(json.dumps({'files': [row], 'errors': []}))
    sql = recovery / 'routes-sqlite'
    sql.mkdir()
    dbfile = sql / 'db.sqlite'
    db = sqlite3.connect(dbfile)
    db.execute('create table example(id integer)')
    db.commit()
    db.close()
    raw = dbfile.read_bytes()
    entry = {'source': 'reconstruction-jobs/job/prepared/database.db', 'backup': 'db.sqlite',
             'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    (sql / 'manifest.json').write_text(json.dumps({'entries': [entry]}))
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    return recovery, workspace


def invoke(recovery, workspace, apply=False, busy=False):
    args = ['import_local_state.py', str(recovery), '--workspace', str(workspace)]
    if apply:
        args.append('--apply')
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.connect_ex.return_value = 0 if busy else 10061
    with patch.object(sys, 'argv', args), patch.object(module.socket, 'socket', return_value=sock):
        module.main()


def test_plan_apply_and_idempotence(fixture):
    recovery, workspace = fixture
    invoke(recovery, workspace)
    assert not (workspace / '.local-pilot').exists()
    invoke(recovery, workspace, apply=True)
    assert (workspace / '.local-pilot/reconstruction-jobs/job/input/video.h264').read_bytes() == b'route input'
    invoke(recovery, workspace, apply=True)


def test_existing_conflict_and_busy_worker_block_before_copy(fixture):
    recovery, workspace = fixture
    with pytest.raises(ValueError, match='occupied'):
        invoke(recovery, workspace, apply=True, busy=True)
    assert not (workspace / '.local-pilot').exists()
    target = workspace / '.local-pilot/reconstruction-jobs/job/input/video.h264'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'other')
    with pytest.raises(ValueError, match='differs'):
        invoke(recovery, workspace, apply=True)
    assert not (workspace / '.local-pilot/reconstruction-jobs/job/prepared').exists()


def test_traversal_and_tamper_rejected_before_copy(fixture):
    recovery, workspace = fixture
    path = recovery / 'routes-essential/manifest.json'
    doc = json.loads(path.read_text())
    doc['files'][0]['source'] = 'reconstruction-jobs/../../escape'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='Unsafe'):
        invoke(recovery, workspace, apply=True)
    doc['files'][0]['source'] = 'reconstruction-jobs/job/input/video.h264'
    path.write_text(json.dumps(doc))
    (recovery / 'routes-essential/blobs' / doc['files'][0]['sha256']).write_bytes(b'tamper')
    with pytest.raises(ValueError, match='mismatch'):
        invoke(recovery, workspace, apply=True)
    assert not (workspace / '.local-pilot').exists()


def test_symlink_destination_rejected_before_copy(fixture):
    recovery, workspace = fixture
    original = Path.is_symlink

    def fake_symlink(path):
        return path == workspace / '.local-pilot/reconstruction-jobs' or original(path)

    with patch.object(Path, 'is_symlink', fake_symlink), pytest.raises(ValueError, match='Symlink'):
        invoke(recovery, workspace, apply=True)
    assert not (workspace / '.local-pilot').exists()
