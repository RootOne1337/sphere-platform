import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.route_replay_snapshot import snapshot,discard_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.dest=self.root/'copy'
        self.nav='navigation/'+('a'*32)
        files={'state.json':{'phase':'sparse_complete'},'control.json':{'key_sha256':'old'},
               'geometry.json':{},'input/manifest.json':{},'navigation/active.json':{'id':'a'*32},
               self.nav+'/state.json':{'phase':'ready'},self.nav+'/route.json':{}}
        for name,value in files.items():
            p=self.source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
        digest=lambda name:hashlib.sha256((self.source/name).read_bytes()).hexdigest()
        (self.source/self.nav/'receipt.json').write_text(json.dumps(dict(sha256=digest(self.nav+'/route.json'),
            geometry_sha256=digest('geometry.json'),source_capture_sha256=digest('input/manifest.json'))))
        (self.source/'input/video.h264').write_bytes(b'large video is not copied')
        (self.source/'prepared').mkdir();(self.source/'prepared/database.db').write_bytes(b'unused database')

    def test_minimal_snapshot_excludes_video_models_and_databases_and_is_independent(self):
        originals={str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        result=snapshot(self.source,self.dest,'b'*64)
        self.assertLess(result['copiedBytes'],2048)
        self.assertFalse((self.dest/'input/video.h264').exists());self.assertFalse((self.dest/'prepared').exists())
        (self.dest/'geometry.json').write_text('fixture mutation')
        self.assertEqual(originals,{str(p.relative_to(self.source)):p.read_bytes() for p in self.source.rglob('*') if p.is_file()})
        self.assertEqual(json.loads((self.dest/'control.json').read_bytes())['key_sha256'],hashlib.sha256(('b'*64).encode()).hexdigest())

    def test_refuses_existing_target_without_overwriting_anything(self):
        self.dest.mkdir();marker=self.dest/'keep';marker.write_text('unchanged')
        with self.assertRaisesRegex(ValueError,'scope'):snapshot(self.source,self.dest,'b'*64)
        self.assertEqual(marker.read_text(),'unchanged')

    def test_bad_binding_and_nonterminal_source_leave_no_snapshot(self):
        for name,value in [(self.nav+'/route.json',{'changed':True}),('state.json',{'phase':'preparing'})]:
            with self.subTest(name=name):
                p=self.source/name;old=p.read_bytes();p.write_text(json.dumps(value))
                with self.assertRaisesRegex(ValueError,'binding|requires_ready'):snapshot(self.source,self.dest,'b'*64)
                self.assertFalse(self.dest.exists());p.write_bytes(old)

    def test_cleanup_preserves_receipt_and_source_and_removes_only_fixture(self):
        snapshot(self.source,self.dest,'b'*64)
        source=(self.source/'geometry.json').read_bytes()
        receipt=self.root/'fixture-receipt.json'
        discard_snapshot(self.dest,receipt)
        self.assertFalse(self.dest.exists())
        self.assertEqual((self.source/'geometry.json').read_bytes(),source)
        self.assertTrue(json.loads(receipt.read_bytes())['temporaryCopiesRemoved'])

    def test_cleanup_refuses_changed_or_unexpected_files_without_deleting_them(self):
        for name in ('geometry.json','unexpected.txt'):
            with self.subTest(name=name):
                destination=self.root/('copy-'+name)
                snapshot(self.source,destination,'b'*64)
                path=destination/name;path.write_text('keep this change')
                with self.assertRaisesRegex(ValueError,'cleanup_changed'):
                    discard_snapshot(destination,self.root/('receipt-'+name))
                self.assertEqual(path.read_text(),'keep this change')


if __name__=='__main__': unittest.main()
