"""Visibility-checked projective texturing of observed surfaces in COLMAP coordinates."""
from __future__ import annotations

import io
import json
import math
import struct

import numpy as np
from PIL import Image

from scripts.pilot.surface_asset import MAX_BYTES, MAX_FACES, MAX_PIXELS, validate_glb


def read_mesh(path):
    if not 0 < path.stat().st_size <= 64 * 1024**2:
        raise ValueError('surface_mesh_byte_quota')
    raw = path.read_bytes()
    end = raw.index(b'end_header\n') + len(b'end_header\n')
    rows = raw[:end].decode('ascii').splitlines()
    # Pinned OpenMVS untextured binary output; reject other layouts explicitly.
    nv = int(next(row.split()[-1] for row in rows if row.startswith('element vertex ')))
    nf = int(next(row.split()[-1] for row in rows if row.startswith('element face ')))
    expected = ['ply', 'format binary_little_endian 1.0', f'element vertex {nv}',
        'property float32 x', 'property float32 y', 'property float32 z', f'element face {nf}',
        'property list uint8 uint32 vertex_indices', 'end_header']
    if [row for row in rows if not row.startswith('comment ')] != expected:
        raise ValueError('surface_mesh_layout_unsupported')
    if not 0 < nv <= MAX_FACES * 3 or not 0 < nf <= MAX_FACES or len(raw) != end + nv * 12 + nf * 13:
        raise ValueError('surface_mesh_count_quota')
    xyz = np.frombuffer(raw, dtype='<f4', offset=end, count=nv * 3).reshape(-1, 3).copy()
    data = np.frombuffer(raw, dtype=np.dtype([('count', 'u1'), ('indices', '<u4', (3,))]),
                         offset=end + nv * 12, count=nf)
    faces = data['indices'].copy()
    if not (data['count'] == 3).all() or faces.max() >= nv or not np.isfinite(xyz).all():
        raise ValueError('surface_mesh_invalid')
    return xyz, faces


def depth_map(view, xy, faces, check):
    """Perspective-correct z-buffer; bounded at 960x540, no hidden-face photo projection."""
    width, height = 960, 540
    depth = np.full((height, width), np.inf)
    screen = xy[faces]
    valid = ((view[faces, 2] > .001).all(1) & np.isfinite(screen).all((1, 2))
             & (screen[:, :, 0].max(1) >= 0) & (screen[:, :, 0].min(1) < width)
             & (screen[:, :, 1].max(1) >= 0) & (screen[:, :, 1].min(1) < height))
    selected = faces[valid]
    triangles = xy[selected]
    low = np.clip(np.floor(triangles.min(1)), [0, 0], [width - 1, height - 1]).astype(int)
    high = np.clip(np.ceil(triangles.max(1)), [0, 0], [width - 1, height - 1]).astype(int)
    extent = (high - low + 1).max(1)
    # Most MVS triangles cover only a few pixels. Batch their exact barycentric
    # z-buffer operations; a bounded slow path handles unusually large triangles.
    previous = 0
    for edge in (4, 8, 16, 32):
        group = np.flatnonzero((extent > previous) & (extent <= edge))
        previous = edge
        for start in range(0, len(group), 256):
            check()
            ids = group[start:start + 256]
            a, b, c = (triangles[ids, index, :, None, None] for index in range(3))
            denominator = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
            nonzero = abs(denominator) >= 1e-6
            denominator = np.where(nonzero, denominator, 1)
            xx = low[ids, 0, None, None] + np.arange(edge)[None, None, :] + .5
            yy = low[ids, 1, None, None] + np.arange(edge)[None, :, None] + .5
            w0 = ((b[:, 1] - c[:, 1]) * (xx - c[:, 0]) + (c[:, 0] - b[:, 0]) * (yy - c[:, 1])) / denominator
            w1 = ((c[:, 1] - a[:, 1]) * (xx - c[:, 0]) + (a[:, 0] - c[:, 0]) * (yy - c[:, 1])) / denominator
            inverse = 1 / view[selected[ids], 2]
            z = 1 / np.maximum(w0 * inverse[:, 0, None, None] + w1 * inverse[:, 1, None, None]
                               + (1 - w0 - w1) * inverse[:, 2, None, None], 1e-9)
            inside = ((w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0) & nonzero
                      & (xx < high[ids, 0, None, None] + 1) & (yy < high[ids, 1, None, None] + 1))
            pixels = ((yy.astype(int) * width) + xx.astype(int))
            np.minimum.at(depth.ravel(), pixels[inside], z[inside])
    for i, face in enumerate(selected[extent > 32]):
        if i % 2000 == 0:
            check()
        t = xy[face]
        x0, y0 = np.clip(np.floor(t.min(0)), [0, 0], [width - 1, height - 1]).astype(int)
        x1, y1 = np.clip(np.ceil(t.max(0)), [0, 0], [width - 1, height - 1]).astype(int)
        a, b, c = t
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-6:
            continue
        yy, xx = np.mgrid[y0:y1 + 1, x0:x1 + 1]
        xx, yy = xx + .5, yy + .5
        w0 = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
        w1 = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
        z = 1 / np.maximum(w0 / view[face[0], 2] + w1 / view[face[1], 2]
                           + (1 - w0 - w1) / view[face[2], 2], 1e-9)
        target = depth[y0:y1 + 1, x0:x1 + 1]
        inside = (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0) & (z < target)
        target[inside] = z[inside]
    return depth


def bake(mesh, cameras, images, output, check, progress=lambda *_: None):
    xyz, faces = read_mesh(mesh)
    if not 3 <= len(cameras) <= 96:
        raise ValueError('surface_view_limit_3_to_96')
    tri = xyz[faces]
    centers = tri.mean(1)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
    scores, chosen, support = np.zeros(len(faces)), np.full(len(faces), -1), np.zeros(len(faces), int)
    for i, camera in enumerate(cameras):
        check()
        k, pose = camera['intrinsics'], np.asarray(camera['camera_to_world'])
        width, height = k['width'], k['height']
        view = (xyz - pose[:, 3]) @ pose[:, :3]
        center_view = (centers - pose[:, 3]) @ pose[:, :3]
        with np.errstate(divide='ignore', invalid='ignore'):
            full = view[:, :2] / view[:, 2, None] * [k['fx'], k['fy']] + [k['cx'], k['cy']]
            cxy = center_view[:, :2] / center_view[:, 2, None] * [k['fx'], k['fy']] + [k['cx'], k['cy']]
        full = np.nan_to_num(full, nan=-1e6, posinf=1e6, neginf=-1e6)
        cxy = np.nan_to_num(cxy, nan=-1e6, posinf=1e6, neginf=-1e6)
        depth = depth_map(view, full * [960 / width, 540 / height], faces, check)
        pxy = full[faces]
        inside = ((view[faces, 2] > .001).all(1) & (pxy[:, :, 0] >= 1).all(1)
                  & (pxy[:, :, 0] < width - 1).all(1) & (pxy[:, :, 1] >= 1).all(1)
                  & (pxy[:, :, 1] < height - 1).all(1))
        ix = np.clip(cxy[:, 0] * 960 / width, 0, 959).astype(int)
        iy = np.clip(cxy[:, 1] * 540 / height, 0, 539).astype(int)
        visible = abs(depth[iy, ix] - center_view[:, 2]) <= np.maximum(center_view[:, 2] * .02, .002)
        mask_file = images / (camera['image'][:-4] + '.mask.png')
        keep = np.ones(len(faces), dtype=bool)
        if mask_file.is_file():
            with Image.open(mask_file) as source:
                mask = np.asarray(source.convert('L'))
            if mask.shape != (height, width):
                raise ValueError('surface_mask_dimensions_changed')
            mx, my = np.clip(cxy[:, 0], 0, width - 1).astype(int), np.clip(cxy[:, 1], 0, height - 1).astype(int)
            vx, vy = np.clip(pxy[:, :, 0], 0, width - 1).astype(int), np.clip(pxy[:, :, 1], 0, height - 1).astype(int)
            keep = (mask[my, mx] > 127) & (mask[vy, vx] > 127).all(1)
        area = abs((pxy[:, 1, 0] - pxy[:, 0, 0]) * (pxy[:, 2, 1] - pxy[:, 0, 1])
                   - (pxy[:, 1, 1] - pxy[:, 0, 1]) * (pxy[:, 2, 0] - pxy[:, 0, 0])) * .5
        direction = pose[:, 3] - centers
        direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-9)
        facing = abs((normals * direction).sum(1))
        good = inside & visible & keep & (facing > .08)
        support += good
        score = np.sqrt(area) * facing
        replace = good & (score > scores)
        scores[replace], chosen[replace] = score[replace], i
        progress(i + 1, len(cameras))
    if (chosen >= 0).sum() < 100:
        raise ValueError('surface_insufficient_visible_triangles')
    model = dict(asset=dict(version='2.0', generator='Sphere projective surface v1'),
        buffers=[], bufferViews=[], accessors=[], images=[], textures=[], materials=[],
        meshes=[dict(primitives=[])], nodes=[dict(mesh=0)], scenes=[dict(nodes=[0])],
        scene=0, extensionsUsed=['KHR_materials_unlit'])
    data = bytearray()

    def append(content):
        index = len(model['bufferViews'])
        model['bufferViews'].append(dict(buffer=0, byteOffset=len(data), byteLength=len(content)))
        data.extend(content)
        data.extend(b'\0' * (-len(data) % 4))
        if len(data) > MAX_BYTES - 2 * 1024**2:
            raise ValueError('surface_asset_byte_quota')
        return index

    def accessor(values, typ, component):
        entry = dict(bufferView=append(values.tobytes()), componentType=component, count=len(values), type=typ)
        if typ == 'VEC3':
            entry.update(min=values.min(0).tolist(), max=values.max(0).tolist())
        index = len(model['accessors'])
        model['accessors'].append(entry)
        return index

    names, photo_sizes = [], []
    for i, camera in enumerate(cameras):
        check()
        subset = faces[chosen == i]
        if not len(subset):
            continue
        k, pose = camera['intrinsics'], np.asarray(camera['camera_to_world'])
        pos = xyz[subset].reshape(-1, 3).astype('<f4')
        view = (pos - pose[:, 3]) @ pose[:, :3]
        xy = view[:, :2] / view[:, 2, None] * [k['fx'], k['fy']] + [k['cx'], k['cy']]
        uv = (xy / [k['width'], k['height']]).astype('<f4')
        with Image.open(images / camera['image']) as source:
            photo = source.convert('RGB')
        edge = min(2048, int(math.sqrt(MAX_PIXELS / len(cameras) * photo.width / photo.height)))
        photo.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        encoded = io.BytesIO()
        photo.save(encoded, format='JPEG', quality=95, subsampling=0)
        material = len(model['materials'])
        model['images'].append(dict(bufferView=append(encoded.getvalue()), mimeType='image/jpeg'))
        model['textures'].append(dict(source=material))
        model['materials'].append(dict(name=f'photo-{material}', doubleSided=True,
            pbrMetallicRoughness=dict(baseColorTexture=dict(index=material), metallicFactor=0),
            extensions={'KHR_materials_unlit': {}}))
        model['meshes'][0]['primitives'].append(dict(attributes=dict(
            POSITION=accessor(pos, 'VEC3', 5126), TEXCOORD_0=accessor(uv, 'VEC2', 5126)),
            indices=accessor(np.arange(len(pos), dtype='<u4').reshape(-1, 1), 'SCALAR', 5125),
            material=material, mode=4))
        names.append(camera['image'])
        photo_sizes.append(list(photo.size))
    model['buffers'] = [dict(byteLength=len(data))]
    metadata = json.dumps(model, separators=(',', ':'), allow_nan=False).encode()
    metadata += b' ' * (-len(metadata) % 4)
    packed = (struct.pack('<4sII', b'glTF', 2, 28 + len(metadata) + len(data))
              + struct.pack('<I4s', len(metadata), b'JSON') + metadata
              + struct.pack('<I4s', len(data), b'BIN\0') + data)
    counts = validate_glb(packed)
    check()
    with output.open('xb') as target:
        target.write(packed)
    return dict(**counts, mesh_faces=len(faces), unknown_faces=int((chosen < 0).sum()),
        multiview_supported_faces=int(((chosen >= 0) & (support >= 2)).sum()),
        source_images=[camera['image'] for camera in cameras], texture_images=names, texture_sizes=photo_sizes)
