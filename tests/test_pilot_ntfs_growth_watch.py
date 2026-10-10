import struct
import unittest
from unittest.mock import patch

from scripts.pilot.ntfs_growth_watch import Journal, growth, records


def record(name='test.txt', major=2, usn=80, file_id=5, reason=2):
    encoded = name.encode('utf-16-le')
    length = (60 + len(encoded) + 7) // 8 * 8
    header = struct.pack('<IHHQQqqIIIIHH', length, major, 0, file_id, 1,
                         usn, 0, reason, 0, 0, 0, len(encoded), 60)
    return header + encoded + b'\x00' * (length - 60 - len(encoded))


class NtfsGrowthTests(unittest.TestCase):
    def reader(self, blocks):
        journal = object.__new__(Journal)
        journal.control = lambda _code, _payload, _capacity: next(blocks)
        return journal

    def test_identity_burst_keeps_bounded_recent_metadata_and_explicit_gap(self):
        blocks = iter(struct.pack('<q', start + 500) + b''.join(
            record(usn=i, file_id=i) for i in range(start, start + 500))
            for start in range(0, 5000, 500))
        with patch('scripts.pilot.ntfs_growth_watch.time.monotonic', return_value=0):
            cursor, changed, used, coverage = self.reader(blocks).read(1, 0, 5000)
        self.assertEqual(cursor, 5000)
        self.assertEqual(len(changed), 4096)
        self.assertEqual(changed[0]['fileId'], 904)
        self.assertEqual(changed[-1]['fileId'], 4999)
        self.assertLess(used, 8 * 1024 ** 2)
        self.assertEqual(coverage['identityObservationsEvicted'], 904)
        self.assertEqual(coverage['state'], 'partial_identity_budget')
        self.assertFalse(coverage['retainedChangedFileCountIsComplete'])

    def test_time_budget_resumes_actual_cursor_without_skipping_unread_records(self):
        journal = self.reader(iter([struct.pack('<q', 100) + record(),
                                    struct.pack('<q', 200) + record(file_id=6)]))
        with patch('scripts.pilot.ntfs_growth_watch.time.monotonic', side_effect=[0, 0, 11]):
            cursor, changed, _used, coverage = journal.read(1, 0, 200)
        self.assertEqual(cursor, 100)
        self.assertEqual(coverage['unreadUsnBytes'], 100)
        self.assertEqual(coverage['state'], 'partial_backlog')
        self.assertEqual(changed[0]['fileId'], 5)
        with patch('scripts.pilot.ntfs_growth_watch.time.monotonic', return_value=0):
            cursor, changed, _used, coverage = journal.read(1, cursor, 200)
        self.assertEqual(cursor, 200)
        self.assertEqual(changed[0]['fileId'], 6)
        self.assertEqual(coverage['state'], 'complete')

    def test_same_identity_updates_latest_record_without_false_eviction(self):
        journal = self.reader(iter([struct.pack('<q', 200) + record(usn=80) + record(usn=100)]))
        _cursor, changed, _used, coverage = journal.read(1, 0, 200)
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]['usn'], 100)
        self.assertEqual(coverage['identityObservationsEvicted'], 0)
        self.assertTrue(coverage['retainedChangedFileCountIsComplete'])

    def test_byte_budget_retains_cursor_and_bounds_device_reads(self):
        journal = object.__new__(Journal)
        calls = []

        def control(_code, payload, capacity):
            calls.append(capacity)
            cursor = struct.unpack_from('<q', payload)[0]
            return struct.pack('<q', cursor + 1) + bytes(capacity - 8)

        journal.control = control
        with patch('scripts.pilot.ntfs_growth_watch.time.monotonic', return_value=0), \
                patch('scripts.pilot.ntfs_growth_watch.records', side_effect=lambda data:
                      (struct.unpack_from('<q', data)[0], [])):
            cursor, changed, used, coverage = journal.read(1, 0, 200)
        self.assertEqual(cursor, 128)
        self.assertEqual(len(calls), 128)
        self.assertEqual(used, 8 * 1024 ** 2)
        self.assertEqual(changed, [])
        self.assertEqual(coverage['state'], 'partial_backlog')
        self.assertEqual(coverage['unreadUsnBytes'], 72)

    def test_nonadvancing_and_unsupported_reads_still_stop_with_explicit_error(self):
        for block in [struct.pack('<q', 0), struct.pack('<q', 100) + record(major=3)]:
            with self.subTest(block=block[:8]), self.assertRaises(ValueError):
                self.reader(iter([block])).read(1, 0, 100)

    def test_unicode_names_identity_reasons_and_multiple_records(self):
        next_usn, rows = records(struct.pack('<q', 200) + record('скрин.png') + record(usn=100, file_id=6))
        self.assertEqual(next_usn, 200)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['name'], 'скрин.png')
        self.assertEqual(rows[0]['reason'], 2)
        self.assertEqual(rows[1]['fileId'], 6)
        self.assertEqual(rows[1]['usn'], 100)

    def test_empty_cursor_only_is_valid(self):
        self.assertEqual(records(struct.pack('<q', 90)), (90, []))

    def test_truncated_cursor_header_or_body_rejected(self):
        for data in [b'123', struct.pack('<q', 100) + b'123',
                     struct.pack('<q', 100) + record()[:-1]]:
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                records(data)

    def test_unsupported_version_is_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            records(struct.pack('<q', 100) + record(major=3))

    def test_invalid_length_alignment_and_filename_bounds_rejected(self):
        for field_offset, fmt, value in [(0, '<I', 0), (0, '<I', 61),
                                         (56, '<H', 3), (58, '<H', 58), (58, '<H', 999)]:
            payload = bytearray(record())
            struct.pack_into(fmt, payload, field_offset, value)
            with self.subTest(offset=field_offset, value=value), self.assertRaises(ValueError):
                records(struct.pack('<q', 100) + payload)

    def test_first_sighting_is_baseline_not_whole_file_growth(self):
        result = growth(None, {'state': 'measured', 'allocatedBytes': 1000000000,
                               'logicalBytes': 1000000000, 'identity': [1, 5]})
        self.assertEqual(result['state'], 'baseline')
        self.assertIsNone(result['allocatedDeltaBytes'])

    def test_same_file_exact_allocation_growth_and_shrink(self):
        first = {'state': 'measured', 'allocatedBytes': 4096, 'logicalBytes': 10, 'identity': [1, 5]}
        second = {**first, 'allocatedBytes': 8192, 'logicalBytes': 5000}
        self.assertEqual(growth(first, second)['allocatedDeltaBytes'], 4096)
        self.assertEqual(growth(second, first)['allocatedDeltaBytes'], -4096)
        self.assertEqual(growth(first, second)['logicalDeltaBytes'], 4990)

    def test_atomic_replacement_and_unavailable_file_are_incomparable(self):
        first = {'state': 'measured', 'allocatedBytes': 4096, 'logicalBytes': 10, 'identity': [1, 5]}
        for second in [{'state': 'unavailable'}, {**first, 'identity': [1, 6]}]:
            with self.subTest(second=second):
                self.assertEqual(growth(first, second)['state'], 'incomparable')

    def test_missing_allocation_still_keeps_exact_logical_delta(self):
        first = {'state': 'measured', 'allocatedBytes': None, 'logicalBytes': 10, 'identity': [1, 5]}
        result = growth(first, {**first, 'logicalBytes': 20})
        self.assertIsNone(result['allocatedDeltaBytes'])
        self.assertEqual(result['logicalDeltaBytes'], 10)


if __name__ == '__main__':
    unittest.main()
