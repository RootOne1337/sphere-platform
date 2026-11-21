"""Self-contained, bounded triangle assets. No URI, decoder or scene extension fetches."""
from __future__ import annotations

import io
import json
import struct

MAX_BYTES = 64 * 1024**2
MAX_PIXELS = 64 * 1024**2
MAX_FACES = 350000


def validate_glb(body):
    """Admit only the small GLB subset emitted by the local surface baker."""
    import numpy as np
    from PIL import Image

    def require(ok):
        if not ok:
            raise ValueError('surface_asset_invalid')

    require(28 < len(body) <= MAX_BYTES)
    require(struct.unpack_from('<4sII', body) == (b'glTF', 2, len(body)))
    size, kind = struct.unpack_from('<I4s', body, 12)
    require(kind == b'JSON' and size % 4 == 0 and 0 < size <= 2 * 1024**2)
    model = json.loads(body[20:20 + size])
    binary_size, kind = struct.unpack_from('<I4s', body, 20 + size)
    require(kind == b'BIN\0' and 28 + size + binary_size == len(body))
    binary = memoryview(body)[28 + size:]
    require(model.get('asset', {}).get('version') == '2.0')
    require(model.get('extensionsUsed', []) == ['KHR_materials_unlit'])
    require(not model.get('extensionsRequired') and not model.get('animations') and not model.get('skins'))
    require(model.get('buffers') == [dict(byteLength=binary_size)])
    require(model.get('scene') == 0 and model.get('scenes') == [dict(nodes=[0])])
    require(model.get('nodes') == [dict(mesh=0)])
    require(len(model.get('meshes', [])) == 1)

    def reject_external(value):
        if isinstance(value, dict):
            require('uri' not in value)
            for key, item in value.items():
                if key == 'extensions':
                    require(item == {'KHR_materials_unlit': {}})
                reject_external(item)
        elif isinstance(value, list):
            for item in value:
                reject_external(item)

    reject_external(model)
    views = model['bufferViews']
    require(0 < len(views) <= 400)
    for view in views:
        require(set(view) <= {'buffer', 'byteOffset', 'byteLength'} and view['buffer'] == 0)
        offset, length = view.get('byteOffset', 0), view['byteLength']
        require(type(offset) is int and type(length) is int and offset >= 0 and length > 0
                and offset % 4 == 0 and offset + length <= binary_size)

    def buffer(index):
        require(type(index) is int and 0 <= index < len(views))
        view = views[index]
        return binary[view.get('byteOffset', 0):view.get('byteOffset', 0) + view['byteLength']]

    accessors = model['accessors']
    require(0 < len(accessors) <= 300)

    def array(index, typ, component):
        require(type(index) is int and 0 <= index < len(accessors))
        entry = accessors[index]
        require(set(entry) <= {'bufferView', 'componentType', 'count', 'type', 'min', 'max'})
        require(entry['componentType'] == component and entry['type'] == typ)
        count, width = entry['count'], {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3}[typ]
        require(type(count) is int and 0 < count <= MAX_FACES * 3)
        payload = buffer(entry['bufferView'])
        require(len(payload) == count * width * 4)
        values = np.frombuffer(payload, dtype='<f4' if component == 5126 else '<u4').reshape(count, width)
        require(bool(np.isfinite(values).all()))
        return values

    pictures, pixels = model['images'], 0
    require(0 < len(pictures) <= 96)
    for entry in pictures:
        require(set(entry) == {'bufferView', 'mimeType'} and entry['mimeType'] == 'image/jpeg')
        with Image.open(io.BytesIO(buffer(entry['bufferView']))) as photo:
            require(photo.format == 'JPEG' and 0 < photo.width <= 2048 and 0 < photo.height <= 2048)
            pixels += photo.width * photo.height
            require(pixels <= MAX_PIXELS)
            photo.verify()
    require(model['textures'] == [dict(source=i) for i in range(len(pictures))])
    materials = model['materials']
    require(len(materials) == len(pictures))
    for i, material in enumerate(materials):
        require(material == dict(name=f'photo-{i}', doubleSided=True,
            pbrMetallicRoughness=dict(baseColorTexture=dict(index=i), metallicFactor=0),
            extensions={'KHR_materials_unlit': {}}))
    triangles, vertices = 0, 0
    primitives = model['meshes'][0]['primitives']
    require(0 < len(primitives) <= len(pictures))
    for primitive in primitives:
        require(set(primitive) == {'attributes', 'indices', 'material', 'mode'} and primitive['mode'] == 4)
        require(type(primitive['material']) is int and 0 <= primitive['material'] < len(materials))
        require(set(primitive['attributes']) == {'POSITION', 'TEXCOORD_0'})
        positions = array(primitive['attributes']['POSITION'], 'VEC3', 5126)
        uv = array(primitive['attributes']['TEXCOORD_0'], 'VEC2', 5126)
        indices = array(primitive['indices'], 'SCALAR', 5125)
        require(len(positions) == len(uv) and len(indices) % 3 == 0 and int(indices.max()) < len(positions))
        require(bool((abs(positions) < 1e6).all()) and bool(((uv >= 0) & (uv <= 1)).all()))
        triangles += len(indices) // 3
        vertices += len(positions)
        require(triangles <= MAX_FACES and vertices <= MAX_FACES * 3)
    return dict(vertices=vertices, triangles=triangles, textures=len(pictures), texture_pixels=pixels)
