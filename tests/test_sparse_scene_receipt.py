import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.sparse_scene_receipt import FILES, create_sparse_receipt, verify_sparse_receipt
from scripts.pilot.prepare_route_workspace import route_source_model


class SparseReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name)
        for name in FILES:
            file = self.job / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'content')
        manifest = self.job/'input/manifest.json'
        manifest.write_text('{}', encoding='utf-8')
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        (self.job/'prepared/reconstruction-input.json').write_text(json.dumps({'source_manifest_sha256': digest}))
        (self.job/'geometry.json').write_text(json.dumps({'source_manifest_sha256': digest}))
        (self.job/'quality.json').write_text(json.dumps(dict(registered=10, selected=10, points=300,
            mean_reprojection_px=1, conditioning={'passed': True}, intrinsics_condition={'passed': True})))

    def test_valid_sparse_model_without_dense_result(self):
        receipt = create_sparse_receipt(self.job)
        self.assertFalse(receipt['execution_qualified'])
        self.assertEqual(verify_sparse_receipt(self.job), receipt)
        self.assertEqual(route_source_model(self.job), self.job/'prepared/sparse/0')
        with self.assertRaisesRegex(ValueError, 'sparse_receipt_already_exists'):
            create_sparse_receipt(self.job)

    def test_changed_model_or_capture_is_rejected(self):
        create_sparse_receipt(self.job)
        (self.job/'prepared/sparse/0/points3D.bin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'sparse_source_changed'):
            route_source_model(self.job)

    def test_optional_model_file_cannot_appear_after_sealing(self):
        create_sparse_receipt(self.job)
        (self.job/'prepared/sparse/0/frames.bin').write_bytes(b'new')
        with self.assertRaisesRegex(ValueError, 'sparse_source_changed'):
            verify_sparse_receipt(self.job)

    def test_rejects_failed_quality_or_unbound_capture(self):
        quality = self.job/'quality.json'
        value = json.loads(quality.read_text()); value['conditioning']['passed'] = False
        quality.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'sparse_quality_gate_failed'):
            create_sparse_receipt(self.job)
        value['conditioning']['passed'] = True; quality.write_text(json.dumps(value))
        (self.job/'input/manifest.json').write_text('{"changed":true}')
        with self.assertRaisesRegex(ValueError, 'sparse_capture_binding_changed'):
            create_sparse_receipt(self.job)
