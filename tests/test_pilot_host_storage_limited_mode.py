import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.pilot import host_storage_watch as watch


class LimitedStorageCollectorTests(unittest.TestCase):
    def identity(self, elevated):
        return SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: elevated))

    def test_non_elevated_default_is_still_rejected(self):
        with patch.object(watch.platform, 'system', return_value='Windows'), \
             patch.object(watch.ctypes, 'windll', self.identity(0), create=True):
            with self.assertRaises(ValueError):
                watch.privilege_mode(allow_unprivileged=False)

    def test_explicit_limited_mode_never_claims_administrator(self):
        with patch.object(watch.platform, 'system', return_value='Windows'), \
             patch.object(watch.ctypes, 'windll', self.identity(0), create=True):
            self.assertFalse(watch.privilege_mode(allow_unprivileged=True))

    def test_elevated_identity_is_measured_in_either_mode(self):
        with patch.object(watch.platform, 'system', return_value='Windows'), \
             patch.object(watch.ctypes, 'windll', self.identity(1), create=True):
            self.assertTrue(watch.privilege_mode(allow_unprivileged=False))
            self.assertTrue(watch.privilege_mode(allow_unprivileged=True))

    def test_limited_flag_does_not_admit_non_windows_host(self):
        with patch.object(watch.platform, 'system', return_value='Linux'):
            with self.assertRaises(ValueError):
                watch.privilege_mode(allow_unprivileged=True)

    def test_default_launch_creates_no_report_and_collects_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'not-created'
            with patch.object(sys, 'argv', ['host-watch', '--output-dir', str(target), '--samples', '2']), \
                 patch.object(watch.platform, 'system', return_value='Windows'), \
                 patch.object(watch.ctypes, 'windll', self.identity(0), create=True), \
                 patch.object(watch, 'collect') as collect:
                with self.assertRaises(SystemExit) as exit_result:
                    watch.main()
                self.assertEqual(exit_result.exception.code, 2)
                self.assertFalse(target.exists())
                collect.assert_not_called()

    def test_unavailable_vss_does_not_prevent_same_boot_ram_trend_or_become_zero(self):
        def snapshot(free, memory):
            return {'freeDiskBytes': free, 'files': {}, 'host': {'state': 'measured', 'value': {
                'bootUtc': '2026-10-07T00:00:00Z', 'availableRamBytes': memory,
                'vss': {'state': 'unavailable', 'rows': [], 'errorType': 'access_denied'},
            }}}
        result = watch.trend(snapshot(1000, 800), snapshot(900, 700))
        self.assertEqual(result['availableRamBytesDelta'], -100)
        self.assertNotIn('vssDeltas', result)
        self.assertEqual(result['writerAttribution'], 'UNDETERMINED')


if __name__ == '__main__':
    unittest.main()
