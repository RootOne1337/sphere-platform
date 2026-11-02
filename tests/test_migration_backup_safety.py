import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.migration import recovery_bundle


def test_missing_source_volume_is_refused_before_destination_or_container(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'migration' / 'backup_data.py'
    spec = importlib.util.spec_from_file_location('migration_backup_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destination = tmp_path / 'backup'
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1)

    with patch.object(sys, 'argv', ['backup_data.py', str(destination)]), \
            patch.object(module.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
            patch.object(module.subprocess, 'run', side_effect=run):
        with pytest.raises(SystemExit, match='Missing source volume'):
            module.main()
    assert not destination.exists()
    assert calls == [['docker', 'volume', 'inspect', module.PREFIX + module.VOLUMES[0]]]


def test_transfer_protects_directory_before_first_file(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'secret').write_bytes(b'private')
    destination = tmp_path / 'backup'

    def protect(path):
        assert path == destination
        assert list(path.iterdir()) == []

    with patch.object(recovery_bundle, 'protect_directory', side_effect=protect) as security:
        recovery_bundle.copy_bundle(source, destination, allow_same_volume=True)
    security.assert_called_once_with(destination)
