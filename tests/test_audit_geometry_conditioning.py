"""Offline interventions stay bound to the actual source and add no input."""
import hashlib
import unittest

from scripts.pilot.audit_geometry_conditioning import make_renderer


class GeometryConditioningTests(unittest.TestCase):
    def test_counterfactuals_are_distinct_and_unknown_frames_are_rejected(self):
        rgb = bytes(192 * 192 * 3)
        digest = hashlib.sha256(rgb).hexdigest()
        renderer = make_renderer({digest: {'points': [[0.5, 0.9], [0.55, 0.7], [0.6, 0.5]], 'yaw': 0.1}}, 192)
        self.assertEqual(renderer(rgb, 192, 'raw', 'cyan_line'), rgb)
        self.assertEqual(renderer(rgb, 192, 'raw_repeat', 'cyan_line'), rgb)
        left = renderer(rgb, 192, 'left', 'cyan_line')
        right = renderer(rgb, 192, 'right', 'cyan_line')
        self.assertNotEqual(left, right)
        with self.assertRaisesRegex(ValueError, 'source_not_bound'):
            renderer(bytes([1]) + rgb[1:], 192, 'straight', 'cyan_line')


if __name__ == '__main__':
    unittest.main()
