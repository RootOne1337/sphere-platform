import hashlib
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from scripts.pilot.alternative_geometry import alternative, list_alternatives, alternative_catalog
from scripts.pilot.reconstruction_service import Jobs, handler


class AlternativeGeometryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name)
        (self.job / 'input').mkdir()
        self.manifest = b'{"clip":"test"}'
        (self.job / 'input/manifest.json').write_bytes(self.manifest)
        self.digest = hashlib.sha256(self.manifest).hexdigest()
        self.folder = self.job / 'alternatives/improved-v1'
        self.folder.mkdir(parents=True)
        data = {'schema': 'sphere-recovered-scene-v1', 'source_manifest_sha256': self.digest,
                'execution_qualified': False, 'cameras': [{}, {}], 'points': []}
        self.body = json.dumps(data).encode()
        (self.folder / 'geometry.json').write_bytes(self.body)
        self.receipt = {'schema': 'sphere-alternative-geometry-v1', 'id': 'improved-v1',
                        'scope': 'DIAGNOSTIC_ONLY', 'execution_qualified': False,
                        'source_manifest_sha256': self.digest,
                        'geometry_sha256': hashlib.sha256(self.body).hexdigest()}
        (self.folder / 'receipt.json').write_text(json.dumps(self.receipt), encoding='utf-8')

    def test_verified_alternative_is_bound_to_the_job(self):
        body, info = alternative(self.job, 'improved-v1')
        self.assertEqual(body, self.body)
        self.assertEqual(info['cameras'], 2)
        self.assertFalse(info['executionQualified'])
        self.assertEqual(list_alternatives(self.job), [info])

    def test_tampering_or_another_source_is_not_listed(self):
        (self.folder / 'geometry.json').write_bytes(self.body + b' ')
        self.assertEqual(list_alternatives(self.job), [])
        with self.assertRaisesRegex(ValueError, 'alternative_geometry_changed'):
            alternative(self.job, 'improved-v1')
        (self.folder / 'geometry.json').write_bytes(self.body)
        (self.job / 'input/manifest.json').write_bytes(b'different')
        self.assertEqual(list_alternatives(self.job), [])

    def test_path_traversal_and_qualified_claims_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'alternative_geometry_id'):
            alternative(self.job, '../input')
        self.receipt['execution_qualified'] = True
        (self.folder / 'receipt.json').write_text(json.dumps(self.receipt), encoding='utf-8')
        self.assertEqual(list_alternatives(self.job), [])

    def write_preference(self, **changes):
        record = {'schema': 'sphere-alternative-selection-v1', 'id': 'improved-v1',
                  'scope': 'DIAGNOSTIC_ONLY', 'execution_qualified': False,
                  'source_manifest_sha256': self.digest,
                  'geometry_sha256': hashlib.sha256(self.body).hexdigest()}
        record.update(changes)
        (self.job / 'alternative-selection.json').write_text(json.dumps(record), encoding='utf-8')

    def test_explicit_bound_review_preference_and_human_label(self):
        self.receipt['label'] = 'Поворот: дополнительные исходные кадры'
        (self.folder / 'receipt.json').write_text(json.dumps(self.receipt), encoding='utf-8')
        self.write_preference()
        result = alternative_catalog(self.job)
        self.assertEqual(result['preferredAlternativeId'], 'improved-v1')
        self.assertEqual(result['alternatives'][0]['label'], self.receipt['label'])
        self.assertFalse(result['alternatives'][0]['executionQualified'])

    def test_no_preference_does_not_choose_the_only_or_largest_result(self):
        result = alternative_catalog(self.job)
        self.assertEqual(len(result['alternatives']), 1)
        self.assertIsNone(result['preferredAlternativeId'])

    def test_stale_cross_source_or_qualified_preference_never_selects(self):
        for changes in ({'id': 'missing'}, {'source_manifest_sha256': '0' * 64},
                        {'geometry_sha256': '0' * 64}, {'execution_qualified': True},
                        {'scope': 'NAVIGATION'}, {'schema': 'other'}):
            with self.subTest(changes=changes):
                self.write_preference(**changes)
                result = alternative_catalog(self.job)
                self.assertIsNone(result['preferredAlternativeId'])
                self.assertEqual(len(result['alternatives']), 1)

    def test_damaged_preference_or_geometry_does_not_make_a_recommendation(self):
        preference = self.job / 'alternative-selection.json'
        for body in ('broken', '[]', 'x' * 4097):
            preference.write_text(body, encoding='utf-8')
            self.assertIsNone(alternative_catalog(self.job)['preferredAlternativeId'])
        self.write_preference()
        (self.folder / 'geometry.json').write_bytes(self.body + b' ')
        self.assertEqual(alternative_catalog(self.job), {'alternatives': [], 'preferredAlternativeId': None})

    def test_unusable_label_does_not_change_bound_geometry(self):
        for label in ('bad\nlabel', 'x' * 121, 1):
            with self.subTest(label=label):
                self.receipt['label'] = label
                (self.folder / 'receipt.json').write_text(json.dumps(self.receipt), encoding='utf-8')
                self.assertNotIn('label', alternative(self.job, 'improved-v1')[1])

    def test_http_access_requires_the_existing_job_capability(self):
        identity, key = 'a' * 32, 'b' * 64
        root = self.job / 'jobs'
        root.mkdir()
        jobs = Jobs(root, self.job / 'python.exe')
        job = root / identity
        job.mkdir()
        (job / 'input').mkdir()
        (job / 'input/manifest.json').write_bytes(self.manifest)
        (job / 'control.json').write_text(json.dumps({'key_sha256': hashlib.sha256(key.encode()).hexdigest()}), encoding='utf-8')
        import shutil
        shutil.copytree(self.job / 'alternatives', job / 'alternatives')
        preference = {'schema': 'sphere-alternative-selection-v1', 'id': 'improved-v1',
                      'scope': 'DIAGNOSTIC_ONLY', 'execution_qualified': False,
                      'source_manifest_sha256': self.digest,
                      'geometry_sha256': hashlib.sha256(self.body).hexdigest()}
        (job / 'alternative-selection.json').write_text(json.dumps(preference), encoding='utf-8')
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(jobs, 'http://127.0.0.1:3015', 0))
        port = server.server_address[1]
        server.RequestHandlerClass = handler(jobs, 'http://127.0.0.1:3015', port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        def get(path, capability):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
            conn.request('GET', path, headers={'X-Sphere-Reconstruction': '1', 'X-Job-Key': capability})
            response = conn.getresponse(); body = response.read(); status = response.status; conn.close()
            return status, body
        path = f'/jobs/{identity}/geometry-alternatives'
        self.assertEqual(get(path, 'wrong')[0], 403)
        status, raw = get(path, key)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['alternatives'][0]['id'], 'improved-v1')
        self.assertEqual(json.loads(raw)['preferredAlternativeId'], 'improved-v1')
        self.assertEqual(get(path + '/improved-v1', key), (200, self.body))


if __name__ == '__main__':
    unittest.main()
