"""Containerd image IDs must bind an entire OCI descriptor chain, never just a tag."""
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.reviewed_image_archive import admit_archive

LIMIT = 8 * 1024 * 1024


class OCIAdmissionTests(unittest.TestCase):
    def make_archive(self, directory, *, index=True, damage=None):
        entries = {}

        def blob(value):
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            digest = hashlib.sha256(raw).hexdigest()
            entries['blobs/sha256/' + digest] = raw
            return {'digest': 'sha256:' + digest, 'size': len(raw)}

        config = {'os': 'linux', 'architecture': 'amd64', 'config': {'User': '1001:1001'}}
        config_ref = blob(config)
        layer = blob(b'fixture layer content')
        manifest = {'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.manifest.v1+json',
                    'config': config_ref, 'layers': [layer]}
        if damage == 'config_size':
            manifest['config'] = {**config_ref, 'size': 1}
        if damage == 'layer_size':
            manifest['layers'] = [{**layer, 'size': 1}]
        target = blob(manifest)
        if index:
            target = blob({'schemaVersion': 2, 'mediaType': 'application/vnd.oci.image.index.v1+json',
                           'manifests': [target]})
        record = {'Config': 'blobs/sha256/' + config_ref['digest'][7:], 'RepoTags': ['example:exact'],
                  'Layers': ['blobs/sha256/' + layer['digest'][7:]]}
        if damage == 'different_layers':
            record['Layers'] = [record['Config']]
        if damage == 'missing_manifest':
            entries.pop('blobs/sha256/' + target['digest'][7:])
        if damage == 'tampered_blob':
            entries[record['Layers'][0]] = b'tampered'
        entries['manifest.json'] = json.dumps([record]).encode()
        archive = directory / 'image.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            for name, value in entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(value)
                output.addfile(member, io.BytesIO(value))
        meta = {'file': 'image.tar.gz', 'bytes': archive.stat().st_size,
                'maxExpandedBytes': LIMIT, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
        return meta, target['digest'], config

    def test_config_is_bound_through_manifest_or_index(self):
        for index in (False, True):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                meta, target, config = self.make_archive(directory, index=index)
                actual, _ = admit_archive(directory, meta, target, 'example:exact',
                    compressed_limit=LIMIT, expanded_limit=LIMIT, json_limit=1024 * 1024)
                self.assertEqual(actual, config)

    def test_digest_descriptors_sizes_and_layer_inventory_cannot_be_substituted(self):
        for damage in ('config_size', 'layer_size', 'different_layers', 'missing_manifest', 'tampered_blob'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                meta, target, _ = self.make_archive(directory, damage=damage)
                with self.assertRaises(ValueError):
                    admit_archive(directory, meta, target, 'example:exact',
                        compressed_limit=LIMIT, expanded_limit=LIMIT, json_limit=1024 * 1024)

    def test_unrelated_digest_cannot_become_image_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            meta, _, _ = self.make_archive(directory)
            with self.assertRaisesRegex(ValueError, 'config digest'):
                admit_archive(directory, meta, 'sha256:' + 'b' * 64, 'example:exact',
                    compressed_limit=LIMIT, expanded_limit=LIMIT, json_limit=1024 * 1024)
