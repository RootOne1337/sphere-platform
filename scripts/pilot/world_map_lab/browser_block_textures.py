"""Keep every source mip and encode large PC rasters for native BC texture streaming."""

import struct

import cv2
import numpy as np


def block_native(data):
    if len(data) < 88 or struct.unpack_from("<I", data)[0] != 9:
        return data
    width, height, depth, levels, _, flags = struct.unpack_from("<HHBBBB", data, 80)
    if (
        max(width, height) <= 64
        or depth != 32
        or flags & 14
        or struct.unpack_from("<I", data, 76)[0] != 21
    ):
        return data
    # ispc_texcomp is needed only when explicitly building this optional profile.
    import ispc_texcomp as bc

    if not levels or not min(width, height):
        raise ValueError("empty native raster")
    offset, mips = 88, []
    for level in range(levels):
        w, h = max(1, width >> level), max(1, height >> level)
        size = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if size != w * h * 4 or size > len(data) - offset:
            raise ValueError("unexpected RGBA mip size")
        image = np.frombuffer(data, np.uint8, size, offset).reshape(h, w, 4)
        mips.append(image)
        offset += size
    if offset != len(data):
        raise ValueError("trailing native raster data")
    alpha = bool(flags & 1 or any(np.any(mip[:, :, 3] != 255) for mip in mips))
    header = bytearray(data[:88])
    header[76:80] = b"DXT5" if alpha else b"DXT1"
    header[87] = flags | 8 | int(alpha)
    out = bytearray(header)
    for mip in mips:
        h, w = mip.shape[:2]
        rgba = cv2.cvtColor(mip, cv2.COLOR_BGRA2RGBA)
        if w % 4 or h % 4:
            rgba = cv2.copyMakeBorder(rgba, 0, -h % 4, 0, -w % 4, cv2.BORDER_REPLICATE)
        ph, pw = rgba.shape[:2]
        surface = bc.RGBASurface(rgba.tobytes(), pw, ph)
        encode = bc.compress_blocks_bc3 if alpha else bc.compress_blocks_bc1
        # The Python binding allocates one byte per pixel for both BC1 and BC3.
        length = (ph // 4) * (pw // 4) * (16 if alpha else 8)
        blocks = encode(surface)[:length]
        if len(blocks) != length:
            raise ValueError("incomplete compressed mip")
        out.extend(struct.pack("<I", length))
        out.extend(blocks)
    return bytes(out)
