"""Occlusion, asset admission and independent surface lifecycle; no native/GPU jobs."""
import hashlib
import json
import struct
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from scripts.pilot import reconstruct_surface as pipeline
from scripts.pilot import reconstruction_service as service
from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_surface import surface_options
from scripts.pilot.surface_asset import validate_glb
from scripts.pilot.surface_bake import bake, depth_map, read_mesh


@pytest.mark.parametrize('body', [{'first_view': -1}, {'view_count': 25}, {'view_count': True},
    {'first_view': 80, 'view_count': 3}, {'extra': 'command'}, {'first_view': 1.5}])
def test_fragment_options_are_bounded_before_native_work(body):
    with pytest.raises(ValueError, match='fragment_range'):
        surface_options(body, 81)


def test_fragment_has_an_explicit_recording_interval():
    assert surface_options({'first_view': 20, 'view_count': 18}, 81) == dict(first_view=20, view_count=18)


def pack(model, binary):
    header = json.dumps(model, separators=(',', ':')).encode()
    header += b' ' * (-len(header) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(header) + len(binary))
            + struct.pack('<I4s', len(header), b'JSON') + header
            + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


@pytest.fixture(scope='module')
def baked(tmp_path_factory):
    folder = tmp_path_factory.mktemp('surface')
    xyz = np.array([[x, y, 3] for y in np.linspace(-.7, .7, 11) for x in np.linspace(-1.2, 1.2, 11)], '<f4')
    faces = []
    for y in range(10):
        for x in range(10):
            a = y * 11 + x
            faces += [[a, a + 1, a + 11], [a + 1, a + 12, a + 11]]
    # Fully hidden behind the foreground plane in every photo.
    xyz = np.concatenate([xyz, np.array([[-.1, -.1, 5], [.1, -.1, 5], [0, .1, 5]], '<f4')])
    faces.append([121, 122, 123])
    encoded = np.zeros(len(faces), np.dtype([('count', 'u1'), ('indices', '<u4', (3,))]))
    encoded['count'], encoded['indices'] = 3, faces
    header = (f'ply\nformat binary_little_endian 1.0\nelement vertex {len(xyz)}\n'
              'property float32 x\nproperty float32 y\nproperty float32 z\n'
              f'element face {len(faces)}\nproperty list uint8 uint32 vertex_indices\nend_header\n').encode()
    mesh = folder / 'mesh.ply'
    mesh.write_bytes(header + xyz.tobytes() + encoded.tobytes())
    cameras = []
    for i in range(3):
        name = f'{i:08}.png'
        Image.new('RGB', (64, 36), (20 + i * 30, 100, 180)).save(folder / name)
        cameras.append(dict(image=name, camera_to_world=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
                            intrinsics=dict(width=64, height=36, fx=40, fy=40, cx=32, cy=18)))
    before = {p.name: p.read_bytes() for p in folder.glob('*.png')}
    counts = bake(mesh, cameras, folder, folder / 'scene.glb', lambda: None)
    assert all((folder / name).read_bytes() == body for name, body in before.items())
    return folder, counts


def test_projective_bake_omits_occluded_faces_and_keeps_source(baked):
    folder, counts = baked
    assert counts['triangles'] == 200
    assert counts['unknown_faces'] == 1
    assert counts['multiview_supported_faces'] == 200
    assert validate_glb((folder / 'scene.glb').read_bytes())['triangles'] == 200


@pytest.mark.parametrize('mutation', ['external', 'nan', 'index', 'pixels', 'extension', 'length'])
def test_asset_rejects_external_resources_and_corrupt_geometry(baked, mutation):
    raw = (baked[0] / 'scene.glb').read_bytes()
    length = struct.unpack_from('<I', raw, 12)[0]
    model = json.loads(raw[20:20 + length])
    binary = bytearray(raw[28 + length:])
    if mutation == 'external':
        model['images'][0]['uri'] = 'https://invalid.example/private'
    elif mutation == 'extension':
        model['extensionsUsed'].append('KHR_draco_mesh_compression')
    elif mutation in {'nan', 'index'}:
        primitive = model['meshes'][0]['primitives'][0]
        entry = model['accessors'][primitive['attributes']['POSITION'] if mutation == 'nan' else primitive['indices']]
        offset = model['bufferViews'][entry['bufferView']]['byteOffset']
        struct.pack_into('<f' if mutation == 'nan' else '<I', binary, offset, float('nan') if mutation == 'nan' else 9999999)
    elif mutation == 'pixels':
        model['images'] *= 97
    elif mutation == 'length':
        binary = binary[:-4]
    with pytest.raises((ValueError, KeyError, struct.error)):
        validate_glb(pack(model, binary))


def test_mesh_rejects_truncated_payload(baked, tmp_path):
    target = tmp_path / 'bad.ply'
    target.write_bytes((baked[0] / 'mesh.ply').read_bytes()[:-1])
    with pytest.raises(ValueError, match='count_quota'):
        read_mesh(target)


@pytest.mark.parametrize('failure', ['missing_cloud', 'empty_cloud', 'missing_mesh'])
def test_successful_native_exit_without_geometry_stops_before_bake(baked, tmp_path, monkeypatch, failure):
    job = tmp_path / 'job'
    output = job / 'surface'
    images = job / 'prepared/images'
    output.mkdir(parents=True)
    images.mkdir(parents=True)
    (output / 'START').touch()
    write_json(output / 'options.json', dict(first_view=0, view_count=3))
    pose = np.column_stack([np.eye(3), np.zeros(3)])
    calibration = np.array([[40, 0, 32], [0, 40, 18], [0, 0, 1]])
    cameras, recovered, provenance = [], {}, []
    for i in range(3):
        name = f'{i:08}.png'
        body = (baked[0] / name).read_bytes()
        (images / name).write_bytes(body)
        cameras.append(dict(image=name, camera_to_world=pose.tolist(),
            intrinsics=dict(width=64, height=36, fx=40, fy=40, cx=32, cy=18)))
        recovered[i] = SimpleNamespace(name=name, camera_id=1,
            cam_from_world=lambda: SimpleNamespace(inverse=lambda: SimpleNamespace(matrix=lambda: pose)))
        provenance.append(dict(image=f'images/{name}', png_sha256=hashlib.sha256(body).hexdigest()))
    write_json(job / 'geometry.json', dict(cameras=cameras))
    write_json(job / 'prepared/reconstruction-input.json', dict(source_manifest_sha256='test', images=provenance))
    rec = SimpleNamespace(images=recovered, cameras={1: SimpleNamespace(calibration_matrix=lambda: calibration)},
        points3D={}, write=lambda _: None)
    monkeypatch.setitem(sys.modules, 'pycolmap', SimpleNamespace(__version__='4.2.1', Reconstruction=lambda _: rec))
    monkeypatch.setattr(pipeline, 'source_model', lambda _: (job / 'prepared/sparse/0',
        dict(source_manifest_sha256='test', geometry_sha256='test')))
    monkeypatch.setattr(pipeline, 'tools_available', lambda: True)
    monkeypatch.setattr(pipeline, 'checkpoint', lambda _: None)
    monkeypatch.setattr(pipeline, 'BINARIES', {})
    monkeypatch.setattr(pipeline, 'bake', lambda *_a, **_k: pytest.fail('bake after empty native output'))
    calls = []

    def native(args, **_):
        name = str(args[0]).replace('\\', '/').rsplit('/', 1)[-1]
        calls.append(name)
        if name == 'InterfaceCOLMAP.exe':
            (output / 'scene.mvs').write_bytes(b'model fixture')
        elif name == 'DensifyPointCloud.exe':
            (output / 'scene_dense.mvs').write_bytes(b'model with no fused geometry')
            if failure != 'missing_cloud':
                vertices = 0 if failure == 'empty_cloud' else 3
                (output / 'scene_dense.ply').write_bytes(f'ply\nformat binary_little_endian 1.0\nelement vertex {vertices}\nend_header\n'.encode())
        return SimpleNamespace(returncode=0, poll=lambda: 0)

    monkeypatch.setattr(pipeline.subprocess, 'Popen', native)
    error = 'surface_mesh_empty' if failure == 'missing_mesh' else 'surface_depth_fusion_empty'
    with pytest.raises(RuntimeError, match=error):
        pipeline.reconstruct(job)
    state = json.loads((output / 'state.json').read_text())
    assert state['phase'] == 'failed' and state['error'] == error
    assert len(calls) == (3 if failure == 'missing_mesh' else 2)
    assert not (output / 'result.json').exists()


@pytest.mark.parametrize('scale', [1, 4])
def test_batched_and_large_triangle_depth_remains_perspective_correct(scale):
    xy = np.array([[5.2, 5.7], [20.1, 6.9], [12.7, 20.3]]) * scale
    view = np.array([[0, 0, 2], [0, 0, 4], [0, 0, 3]])
    depth = depth_map(view, xy, np.array([[0, 1, 2]]), lambda: None)
    x, y = 12 * scale, 12 * scale
    weights = np.linalg.solve(np.vstack([xy.T, np.ones(3)]), [x + .5, y + .5, 1])
    assert (weights >= 0).all()
    assert depth[y, x] == pytest.approx(1 / (weights / view[:, 2]).sum(), rel=1e-12)


@pytest.fixture
def ready_job(baked, tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'collect', lambda _: {})
    monkeypatch.setattr(service, 'evaluate', lambda _: [])
    jobs = service.Jobs(tmp_path / 'jobs', tmp_path / 'python.exe')
    jobs.create(dict(id='a' * 32, key='b' * 64, steps=3000, mask='none'))
    job = jobs.path('a' * 32)
    write_json(job / 'state.json', dict(phase='complete'))
    (job / 'COMPLETE').touch()
    (job / 'geometry.json').write_text('{}')
    (job / 'input/manifest.json').write_text('{}')
    folder = job / 'surface'
    folder.mkdir()
    raw = (baked[0] / 'scene.glb').read_bytes()
    (folder / 'scene.glb').write_bytes(raw)
    write_json(folder / 'result.json', dict(schema='sphere-observed-surface-v1', file='scene.glb',
        sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), **baked[1], metric_scale=None,
        navigation_qualified=False, geometry_sha256=hashlib.sha256(b'{}').hexdigest(),
        source_manifest_sha256=hashlib.sha256(b'{}').hexdigest(), seconds=1))
    write_json(folder / 'state.json', dict(phase='ready'))
    return jobs, job, raw


def test_surface_asset_binds_source_and_does_not_admit_tampering(ready_job):
    jobs, job, raw = ready_job
    assert jobs.status(job)['surface']['available']
    assert jobs.surface_asset(job) == raw
    (job / 'surface/scene.glb').write_bytes(raw[:-1] + b'x')
    with pytest.raises(ValueError, match='asset_changed'):
        jobs.surface_asset(job)
    (job / 'geometry.json').write_text('{"changed":true}')
    assert jobs.status(job)['surface']['phase'] == 'failed'


def test_active_surface_blocks_other_jobs_and_restart_cannot_publish_late_ready(ready_job):
    jobs, job, _ = ready_job
    write_json(job / 'surface/state.json', dict(phase='baking'))
    with pytest.raises(ValueError, match='one_active'):
        jobs.create(dict(id='c' * 32, key='d' * 64, steps=3000, mask='none'))
    restarted = service.Jobs(jobs.folder, jobs.python)
    assert restarted.status(job)['surface']['error'] == 'surface_service_restarted'
    assert (job / 'surface/CANCEL').is_file()
    write_json(job / 'surface/state.json', dict(phase='ready'))
    assert not restarted.status(job)['surface']['available']
    with pytest.raises(ValueError, match='not_ready'):
        restarted.surface_asset(job)


def test_existing_surface_intent_is_not_repeated(ready_job, monkeypatch):
    jobs, job, _ = ready_job
    monkeypatch.setattr(service.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('repeated work'))
    assert jobs.start_surface(job)['surface']['available']
    write_json(job / 'surface/state.json', dict(phase='failed', error='unknown'))
    assert jobs.start_surface(job)['surface']['phase'] == 'failed'


def test_multiple_fragments_keep_the_original_and_have_separate_cancellation(ready_job):
    jobs, job, body = ready_job
    identity = 'c' * 32
    folder = job / 'fragments' / identity
    folder.parent.mkdir()
    # A known source copy is a test fixture, not another native job.
    import shutil
    shutil.copytree(job / 'surface', folder)
    write_json(folder / 'options.json', dict(first_view=0, view_count=3))
    assert jobs.status(job)['surface']['available']
    assert jobs.status(job)['fragments'][0]['id'] == identity
    assert jobs.surface_asset(job, identity) == body
    (folder / 'CANCEL').touch()
    assert not jobs.surface_status(job, identity)['available']
    assert jobs.surface_asset(job) == body


def test_fragment_restart_blocks_late_result_and_global_admission(ready_job):
    jobs, job, _ = ready_job
    folder = job / 'fragments' / ('c' * 32)
    folder.mkdir(parents=True)
    write_json(folder / 'state.json', dict(phase='densifying'))
    with pytest.raises(ValueError, match='one_active'):
        jobs.create(dict(id='d' * 32, key='e' * 64, steps=3000, mask='none'))
    service.Jobs(jobs.folder, jobs.python)
    assert json.loads((folder / 'state.json').read_text())['phase'] == 'failed'
    assert (folder / 'CANCEL').exists()
    assert jobs.surface_asset(job)


@pytest.mark.parametrize('identity', ['../escape', 'x' * 32, '', 'a' * 33])
def test_fragment_paths_never_escape_the_job(ready_job, identity):
    jobs, job, _ = ready_job
    with pytest.raises(ValueError, match='fragment_id'):
        jobs.surface_asset(job, identity)


def test_original_frame_preview_checks_hash_and_preserves_pixels(ready_job, baked, monkeypatch):
    jobs, job, _ = ready_job
    name = '00000000.png'
    folder = job / 'prepared/images'
    folder.mkdir(parents=True)
    raw = (baked[0] / name).read_bytes()
    (folder / name).write_bytes(raw)
    write_json(job / 'prepared/reconstruction-input.json', dict(images=[dict(image='images/' + name, png_sha256=hashlib.sha256(raw).hexdigest())]))
    calls = []
    monkeypatch.setattr(service, 'source_model', lambda target: calls.append(target))
    jpeg = jobs.source_preview(job, name)
    assert jpeg.startswith(b'\xff\xd8') and calls == [job]
    assert (folder / name).read_bytes() == raw
    (folder / name).write_bytes(raw + b'changed')
    with pytest.raises(ValueError, match='preview_changed'):
        jobs.source_preview(job, name)
    for invalid in ('../control.json', '00000000.jpg', 'http://example.com'):
        with pytest.raises(ValueError, match='preview_invalid'):
            jobs.source_preview(job, invalid)


def test_visual_review_cannot_attach_to_a_different_asset(ready_job):
    jobs, job, body = ready_job
    review = dict(schema='sphere-surface-visual-review-v1', asset_sha256='0' * 64,
                  state='issues_found', issues=['holes', 'occluding_surfaces'])
    write_json(job / 'surface/visual-review.json', review)
    assert 'visual_review' not in jobs.surface_status(job)
    review['asset_sha256'] = hashlib.sha256(body).hexdigest()
    write_json(job / 'surface/visual-review.json', review)
    assert jobs.surface_status(job)['visual_review']['issues'] == ['holes', 'occluding_surfaces']


def test_camera_motion_warning_never_accepts_navigation(ready_job):
    jobs, job, _ = ready_job
    geometry = dict(cameras=[dict(image=f'{i:08}.png', ticks_90k=i * 45000, center=[i % 2, 0, 0]) for i in range(7)])
    write_json(job / 'geometry.json', geometry)
    motion = jobs.status(job)['camera_motion']
    assert motion['warning'] == 'poses_require_temporal_review'
    assert motion['rapid_reversals'] == 5
    assert motion['navigation_qualified'] is False


def test_forward_camera_jump_is_visible_in_job_diagnostics(ready_job):
    jobs, job, _ = ready_job
    geometry = dict(cameras=[dict(image=f'{i:08}.png', ticks_90k=i * 45000, center=[x, 0, 0])
        for i, x in enumerate([0, 1, 2, 3, 4, 34, 35, 36])])
    write_json(job / 'geometry.json', geometry)
    motion = jobs.status(job)['camera_motion']
    assert motion['warning'] == 'poses_require_temporal_review'
    assert motion['rapid_reversals'] == 0
    assert motion['speed_outliers'] == 1
    assert motion['navigation_qualified'] is False


def test_surface_http_uses_same_capability_and_embedded_binary_type(ready_job):
    import threading
    import urllib.error
    import urllib.request
    from http.server import ThreadingHTTPServer

    jobs, job, raw = ready_job
    server = ThreadingHTTPServer(('127.0.0.1', 0), service.handler(jobs, 'http://127.0.0.1:3015', 3342))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/jobs/{job.name}/surface'
    try:
        for key in ('', 'f' * 64):
            request = urllib.request.Request(url, headers={'Host': '127.0.0.1:3342', 'X-Sphere-Reconstruction': '1', 'X-Job-Key': key})
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            assert error.value.code == 403
        request = urllib.request.Request(url, headers={'Host': '127.0.0.1:3342', 'Origin': 'http://127.0.0.1:3015',
            'X-Sphere-Reconstruction': '1', 'X-Job-Key': 'b' * 64})
        with urllib.request.urlopen(request) as response:
            assert response.headers['Content-Type'] == 'model/gltf-binary'
            assert response.headers['Cache-Control'] == 'no-store'
            assert response.read() == raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
