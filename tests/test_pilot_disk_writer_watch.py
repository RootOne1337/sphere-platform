import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.pilot import disk_writer_watch as watch

AT = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
KEY = ('volume-c', 'volume-c')


def sample(at=AT, free=1000, allocated=10, maximum=80, boot='2026-10-07T00:00:00Z'):
    return {'observedAt': at.isoformat(), 'freeDiskBytes': free,
            'host': {'state': 'measured', 'value': {'bootUtc': boot,
                'vss': {'state': 'measured', 'rows': [{
                    'volume': KEY[0], 'diffVolume': KEY[1],
                    'allocatedBytes': allocated, 'maxBytes': maximum}]}}}}


class DiskWriterWatchTests(unittest.TestCase):
    def current(self, **kwargs):
        return watch.observation(sample(**kwargs), AT + timedelta(seconds=120))

    def test_cumulative_loss_triggers_even_when_each_step_is_small(self):
        tracker = watch.Trigger(128)
        self.assertEqual(tracker.inspect(self.current()), [])
        self.assertEqual(tracker.inspect(self.current(at=AT + timedelta(seconds=30), free=930)), [])
        self.assertEqual(tracker.inspect(self.current(at=AT + timedelta(seconds=60), free=870)),
                         ['free_space_drop'])

    def test_user_cleanup_sets_new_peak_and_rearm_excludes_old_loss(self):
        tracker = watch.Trigger(128)
        tracker.inspect(self.current())
        tracker.inspect(self.current(at=AT + timedelta(seconds=30), free=2000))
        current = self.current(at=AT + timedelta(seconds=60), free=1870)
        self.assertEqual(tracker.inspect(current), ['free_space_drop'])
        tracker.rearm(current)
        self.assertEqual(tracker.inspect(self.current(at=AT + timedelta(seconds=90), free=1800)), [])

    def test_repeated_sample_and_older_timestamp_do_not_trigger(self):
        tracker = watch.Trigger(128)
        tracker.inspect(self.current())
        self.assertEqual(tracker.inspect(self.current(free=100)), [])
        self.assertEqual(tracker.inspect(self.current(at=AT - timedelta(seconds=30), free=100)), [])

    def test_boot_change_rebaselines_incomparable_counters(self):
        tracker = watch.Trigger(128)
        tracker.inspect(self.current())
        self.assertEqual(tracker.inspect(self.current(at=AT + timedelta(seconds=30), free=100,
            allocated=1000, maximum=1, boot='2026-10-07T00:30:00Z')), [])

    def test_vss_growth_is_exact_and_quota_change_has_separate_reason(self):
        tracker = watch.Trigger(128)
        tracker.inspect(self.current())
        self.assertEqual(tracker.inspect(self.current(at=AT + timedelta(seconds=30),
            allocated=150, maximum=160)), ['vss_allocation_growth', 'vss_quota_changed'])

    def test_unavailable_vss_is_not_zero_or_membership_change(self):
        tracker = watch.Trigger(128)
        tracker.inspect(self.current())
        missing = sample(at=AT + timedelta(seconds=30))
        missing['host']['value']['vss'] = {'state': 'unavailable', 'rows': []}
        self.assertEqual(tracker.inspect(watch.observation(missing, AT + timedelta(seconds=120))), [])
        self.assertEqual(tracker.inspect(self.current(at=AT + timedelta(seconds=60), maximum=160)),
                         ['vss_quota_changed'])

    def test_measured_membership_change_does_not_invent_old_allocation(self):
        tracker = watch.Trigger(128)
        tracker.inspect(self.current())
        empty = sample(at=AT + timedelta(seconds=30))
        empty['host']['value']['vss']['rows'] = []
        self.assertEqual(tracker.inspect(watch.observation(empty, AT + timedelta(seconds=120))),
                         ['vss_membership_changed'])

    def test_unknown_host_still_allows_exact_disk_measurement(self):
        value = sample()
        value['host'] = {'state': 'unavailable'}
        observed = watch.observation(value, AT)
        self.assertIsNone(observed.vss)
        self.assertEqual(observed.free, 1000)

    def test_stale_future_naive_or_non_utc_sample_is_rejected(self):
        for at in [AT - timedelta(seconds=361), AT + timedelta(seconds=1),
                   AT.replace(tzinfo=None), AT.astimezone(timezone(timedelta(hours=5)))]:
            with self.subTest(at=at), self.assertRaises(ValueError):
                watch.observation(sample(at=at), AT)

    def test_bool_negative_and_duplicate_counters_are_not_valid_measurements(self):
        for field, value in [('freeDiskBytes', True), ('freeDiskBytes', -1)]:
            invalid = sample()
            invalid[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                watch.observation(invalid, AT)
        for field, value in [('maxBytes', True), ('allocatedBytes', -1)]:
            invalid = sample()
            invalid['host']['value']['vss']['rows'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                watch.observation(invalid, AT)
        invalid = sample()
        invalid['host']['value']['vss']['rows'] *= 2
        with self.assertRaises(ValueError):
            watch.observation(invalid, AT)

    def test_partial_append_keeps_last_complete_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'samples.jsonl'
            path.write_bytes(json.dumps(sample()).encode() + b'\n{"observedAt":')
            self.assertEqual(watch.read_latest(path), sample())

    def test_tail_discards_old_records_without_reading_whole_history(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'samples.jsonl'
            path.write_bytes((b'{"padding":"' + b'a' * 70000 + b'"}\n') * 20
                             + json.dumps(sample()).encode() + b'\n')
            self.assertEqual(watch.read_latest(path), sample())

    def test_oversized_last_record_or_duplicate_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'samples.jsonl'
            for content in [b'a' * (watch.SAMPLE_LIMIT * 3) + b'\n', b'{"x":1,"x":2}\n']:
                path.write_bytes(content)
                with self.assertRaises(ValueError):
                    watch.read_latest(path)

    def test_timed_out_capture_is_unknown_and_child_is_not_killed(self):
        child = Mock(pid=42)
        child.communicate.side_effect = watch.subprocess.TimeoutExpired('powershell', 840)
        with patch.object(watch.subprocess, 'Popen', return_value=child), \
             patch.dict(watch.os.environ, {'SystemRoot': 'C:/Windows'}):
            result = watch.run_capture(Path('.'), 600)
        self.assertEqual(result['state'], 'unknown_child_timeout')
        self.assertFalse(result['childKilled'])
        child.kill.assert_not_called()
        child.terminate.assert_not_called()

    def test_child_report_must_stay_in_private_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            foreign = root / 'foreign'
            foreign.mkdir()
            child = Mock(pid=1, returncode=0)
            child.communicate.return_value = (json.dumps({'state': 'complete',
                'reportDirectory': str(foreign)}).encode(), b'')
            with patch.object(watch.subprocess, 'Popen', return_value=child), \
                 patch.dict(watch.os.environ, {'SystemRoot': 'C:/Windows'}), \
                 self.assertRaises(ValueError):
                watch.run_capture(root, 600)


if __name__ == '__main__':
    unittest.main()
