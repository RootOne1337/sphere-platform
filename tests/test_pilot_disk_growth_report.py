import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import disk_growth_report as report


def sample(index=0, free=1000, allocation=100, identity=None):
    return {
        'sample': index, 'observedAt': f'2026-10-07T03:{index * 5:02d}:00+00:00',
        'freeDiskBytes': free,
        'watchedFiles': {'C:\\private\\disk.vhdx': {
            'state': 'measured', 'logicalBytes': 500, 'allocatedBytes': allocation,
            'identity': [1, 2] if identity is None else identity,
        }},
    }


class DiskGrowthReportTests(unittest.TestCase):
    def test_fixed_vhd_with_host_free_drop_never_identifies_writer(self):
        result = report.summarize([sample(), sample(1, 700)])
        self.assertEqual(result['freeDeltaBytes'], -300)
        self.assertEqual(result['elapsedSeconds'], 300)
        self.assertEqual(result['watchedFiles'][0]['allocatedDeltaBytes'], 0)
        self.assertTrue(result['watchedFiles'][0]['allocatedConstantThroughout'])
        self.assertEqual(result['writerAttribution'], 'UNDETERMINED')

    def test_sparse_allocation_growth_is_distinct_from_logical_length(self):
        result = report.summarize([sample(allocation=100), sample(1, allocation=400)])
        watched = result['watchedFiles'][0]
        self.assertEqual(watched['allocatedDeltaBytes'], 300)
        self.assertEqual(watched['logicalDeltaBytes'], 0)
        self.assertFalse(watched['allocatedConstantThroughout'])

    def test_allocation_missing_in_middle_cannot_be_zero_growth(self):
        result = report.summarize([sample(), sample(1, allocation=None), sample(2)])
        watched = result['watchedFiles'][0]
        self.assertFalse(watched['allocationComplete'])
        self.assertIsNone(watched['allocatedDeltaBytes'])
        self.assertIsNone(watched['allocatedConstantThroughout'])

    def test_growth_returning_to_baseline_is_not_constant(self):
        result = report.summarize([sample(), sample(1, allocation=400), sample(2)])
        watched = result['watchedFiles'][0]
        self.assertEqual(watched['allocatedDeltaBytes'], 0)
        self.assertFalse(watched['allocatedConstantThroughout'])

    def test_replaced_identity_does_not_become_same_file_delta(self):
        watched = report.summarize([sample(), sample(1, identity=[1, 9])])['watchedFiles'][0]
        self.assertFalse(watched['sameIdentityThroughout'])
        self.assertIsNone(watched['logicalDeltaBytes'])
        self.assertIsNone(watched['allocatedDeltaBytes'])

    def test_zero_identity_is_unknown_even_when_observed_length_is_constant(self):
        watched = report.summarize([sample(identity=[0, 0]), sample(1, identity=[0, 0])])['watchedFiles'][0]
        self.assertFalse(watched['sameIdentityThroughout'])
        self.assertTrue(watched['observedLogicalConstant'])
        self.assertIsNone(watched['logicalDeltaBytes'])

    def test_unavailable_or_disappearing_watched_file_preserves_unknown(self):
        for inventory in ({}, {'C:\\private\\disk.vhdx': {'state': 'unavailable'}}):
            with self.subTest(inventory=inventory):
                later = sample(1)
                later['watchedFiles'] = inventory
                watched = report.summarize([sample(), later])['watchedFiles'][0]
                self.assertEqual(watched['measuredSamples'], 1)
                self.assertIsNone(watched['allocatedDeltaBytes'])
                self.assertIsNone(watched['observedLogicalConstant'])

    def test_sequence_gap_is_reported_and_not_silently_interpolated(self):
        result = report.summarize([sample(), sample(2)])
        self.assertEqual(result['missingSequenceIntervals'], 1)
        self.assertEqual(result['maximumIntervalSeconds'], 600)

    def test_offset_is_normalized_without_assuming_host_timezone(self):
        first = sample()
        first['observedAt'] = '2026-10-07T08:00:00+05:00'
        result = report.summarize([first, sample(1)])
        self.assertEqual(result['startedUtc'], '2026-10-07T03:00:00+00:00')
        self.assertEqual(result['elapsedSeconds'], 300)

    def test_backward_timestamp_duplicate_index_and_naive_time_are_rejected(self):
        for field, value in [('sample', 0), ('observedAt', '2026-10-07T02:59:00+00:00'),
                             ('observedAt', '2026-10-07T03:05:00')]:
            with self.subTest(field=field, value=value):
                later = sample(1)
                later[field] = value
                with self.assertRaises(ValueError):
                    report.summarize([sample(), later])

    def test_invalid_counters_are_rejected_without_coercion(self):
        for value in (True, -1, '100', 100.0, 2**63):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    report.summarize([sample(free=value)])
                with self.assertRaises(ValueError):
                    report.summarize([sample(allocation=value)])

    def test_input_and_private_paths_are_not_mutated_or_emitted(self):
        source = [sample(), sample(1)]
        before = copy.deepcopy(source)
        result = report.summarize(source)
        self.assertEqual(source, before)
        self.assertNotIn('private', json.dumps(result))
        self.assertNotIn('disk.vhdx', json.dumps(result))

    def test_single_sample_has_no_interval_or_drop_claim(self):
        result = report.summarize([sample()])
        self.assertIsNone(result['minimumIntervalSeconds'])
        self.assertEqual(result['largestObservedDrops'], [])
        self.assertEqual(result['elapsedSeconds'], 0)

    def test_reader_ignores_status_and_temporary_files_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            original = json.dumps(sample()).encode()
            (directory / 'sample-000.json').write_bytes(original)
            (directory / 'sample-001.json.tmp').write_text('incomplete', encoding='utf-8')
            (directory / 'status.json').write_text('{}', encoding='utf-8')
            samples, size = report.load_samples(directory)
            self.assertEqual(size, len(original))
            self.assertEqual(samples, [sample()])
            self.assertEqual((directory / 'sample-000.json').read_bytes(), original)

    def test_reader_rejects_duplicate_keys_filename_mismatch_and_oversize(self):
        for payload in (b'{"sample":0,"sample":0}', json.dumps(sample(1)).encode(),
                        b' ' * (report.MAX_SAMPLE_BYTES + 1)):
            with self.subTest(size=len(payload)), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                (directory / 'sample-000.json').write_bytes(payload)
                with self.assertRaises(ValueError):
                    report.load_samples(directory)

    def test_reader_requires_a_finite_nonempty_sample_set(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                report.load_samples(Path(folder))
        with self.assertRaises(ValueError):
            report.summarize([sample()] * (report.MAX_SAMPLES + 1))

    def test_reader_enforces_total_budget_before_reading_all_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            payload = json.dumps(sample()).encode()
            (directory / 'sample-000.json').write_bytes(payload)
            (directory / 'sample-001.json').write_text(json.dumps(sample(1)), encoding='utf-8')
            with patch.object(report, 'MAX_TOTAL_BYTES', len(payload) + 5):
                with self.assertRaisesRegex(ValueError, 'sample_storage_budget'):
                    report.load_samples(directory)

    def test_reader_does_not_traverse_unbounded_unrelated_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'sample-000.json').write_text(json.dumps(sample()), encoding='utf-8')
            for index in range(4):
                (directory / f'unrelated-{index}').touch()
            with patch.object(report, 'MAX_ENTRIES', 4):
                with self.assertRaisesRegex(ValueError, 'directory_entry_budget'):
                    report.load_samples(directory)

    def test_invalid_inventory_and_logical_counter_are_rejected(self):
        for inventory in (None, [], {'path': {'state': 'measured', 'logicalBytes': True}}):
            with self.subTest(inventory=inventory):
                source = sample()
                source['watchedFiles'] = inventory
                with self.assertRaises(ValueError):
                    report.summarize([source])


if __name__ == '__main__':
    unittest.main()
