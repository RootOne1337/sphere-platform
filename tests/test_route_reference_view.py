import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from motor_worker.route_reference_view import reference_rotations
from tests import test_motor_route_localization as fixtures


class ReferenceViewTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.SparseLocalizationTests('test_blank_real_rgb_has_no_pose');fixture.setUp()
        self.route=fixture.route;self.np=fixture.np
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'geometry.json'
        self.data=dict(source_manifest_sha256=self.route.source_capture_sha256,cameras=[dict(ticks_90k=round(t*90000),
            camera_to_world=self.np.c_[self.np.eye(3),center].tolist()) for t,center in zip(self.route.source_seconds,self.route.camera_trace)])

    def load(self):
        raw=json.dumps(self.data).encode();self.path.write_bytes(raw)
        return reference_rotations(self.path,self.route,hashlib.sha256(raw).hexdigest())

    def test_exact_geometry_and_source_bind_recorded_views(self):
        result=self.load();self.assertEqual(len(result),len(self.route.camera_trace))
        self.np.testing.assert_allclose(result[2],self.np.eye(3))
        with self.assertRaisesRegex(ValueError,'changed'):reference_rotations(self.path,self.route,'f'*64)

    def test_changed_source_center_ticks_or_reflection_cannot_supply_a_view(self):
        import copy
        original=copy.deepcopy(self.data)
        for mutation in ('source','center','tick','reflection'):
            self.data=copy.deepcopy(original)
            if mutation=='source':self.data['source_manifest_sha256']='d'*64
            if mutation=='center':self.data['cameras'][0]['camera_to_world'][0][3]+=1
            if mutation=='tick':self.data['cameras'][0]['ticks_90k']=100
            if mutation=='reflection':self.data['cameras'][0]['camera_to_world'][0][0]=-1
            self.assertIsNone(self.load())

    def test_legacy_geometry_has_no_implicit_vertical_orientation(self):
        self.data={};self.assertIsNone(self.load())
