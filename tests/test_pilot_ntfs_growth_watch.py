import struct
import unittest

from scripts.pilot.ntfs_growth_watch import growth, records


def record(name='test.txt', major=2, usn=80, file_id=5, reason=2):
    encoded = name.encode('utf-16-le')
    length = (60 + len(encoded) + 7) // 8 * 8
    header = struct.pack('<IHHQQqqIIIIHH', length, major, 0, file_id, 1,
                         usn, 0, reason, 0, 0, 0, len(encoded), 60)
    return header + encoded + b'\x00' * (length - 60 - len(encoded))


class NtfsGrowthTests(unittest.TestCase):
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
