import io
import sys
import tarfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.migration import backup_other_volumes as backup


def test_missing_volume_refused_without_starting_container(tmp_path):
    with patch.object(backup.subprocess, 'run', return_value=SimpleNamespace(returncode=1)), \
            patch.object(backup.subprocess, 'Popen') as start:
        with pytest.raises(ValueError, match='missing'):
            backup.capture_volume('missing-volume', tmp_path / 'data.tar.gz', 0, {})
    start.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_recreated_volume_identity_rejected():
    original = {'Name': 'data', 'CreatedAt': 'before', 'Driver': 'local', 'Options': {}, 'Labels': {}}
    replacement = {**original, 'CreatedAt': 'after'}
    with patch.object(backup, 'must_exist', return_value=replacement):
        with pytest.raises(ValueError, match='identity changed'):
            backup.ensure_unchanged('data', original)


def test_replacement_after_archive_never_marks_complete(tmp_path):
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode='w:gz') as archive:
        info = tarfile.TarInfo('file')
        info.size = 4
        archive.addfile(info, io.BytesIO(b'data'))
    process = SimpleNamespace(stdout=io.BytesIO(content.getvalue()), wait=lambda: 0, poll=lambda: 0)
    target = tmp_path / 'data.tar.gz'
    with patch.object(backup, 'ensure_unchanged', side_effect=[None, ValueError('identity changed')]), \
            patch.object(backup.subprocess, 'Popen', return_value=process), \
            patch.object(backup.subprocess, 'run'):
        with pytest.raises(ValueError, match='identity changed'):
            backup.capture_volume('data', target, 0, {})
    assert not target.exists()
    assert (tmp_path / 'data.tar.gz.partial').exists()


def test_plan_is_read_only_and_reports_volumes(tmp_path, capsys):
    target = tmp_path / 'unused'
    with patch.object(sys, 'argv', ['backup_other_volumes.py', str(target), '--plan']), \
            patch.object(backup, 'inventory', return_value=[('one', '10MB')]), \
            patch.object(backup, 'must_exist') as inspect, \
            patch.object(backup, 'capture_volume') as capture:
        backup.main()
    inspect.assert_called_once_with('one')
    capture.assert_not_called()
    assert not target.exists()
    assert 'one\t10MB' in capsys.readouterr().out
