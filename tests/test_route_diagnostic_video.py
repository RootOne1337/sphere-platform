"""Browser diagnostic export validation with a real H.264 stream."""

import hashlib
import json
from fractions import Fraction

import numpy as np
import pytest

from motor_worker.protocol import ProtocolError
from motor_worker.teach_capture import nal_types
from scripts.pilot.route_diagnostic_video import decoded_diagnostic_video, validate_diagnostic_video


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def exported(tmp_path):
    av = pytest.importorskip("av")
    codec = av.CodecContext.create("libx264", "w")
    codec.width, codec.height, codec.pix_fmt = 64, 48, "yuv420p"
    codec.time_base, codec.framerate = Fraction(1, 30), Fraction(30)
    codec.options = {"preset": "ultrafast", "tune": "zerolatency", "repeat-headers": "1"}
    packets = []
    for index in range(8):
        frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), 30+index, dtype=np.uint8), format="rgb24")
        frame.pts = index
        packets.extend(bytes(packet) for packet in codec.encode(frame))
    packets.extend(bytes(packet) for packet in codec.encode(None))
    video = b"".join(packets)
    index_rows, offset = [], 0
    for index, packet in enumerate(packets):
        types = set(nal_types(packet))
        index_rows.append(dict(
            index=index, offset=offset, bytes=len(packet), rtp_timestamp=(2**32-2000 + index*3000) % 2**32,
            relative_ticks_90k=index*3000, worker_observed_at_ms=1020 + index*34,
            geometry_reported=bool(types & {5, 7, 8}), key=5 in types,
            seekable={5, 7, 8}.issubset(types), sha256=digest(packet),
        ))
        offset += len(packet)
    files = tuple(tmp_path/name for name in ("sphere-vehicle.h264", "sphere-vehicle.jsonl", "sphere-vehicle.json"))
    meta = dict(
        schema="sphere-vehicle-video-v1", runId="a"*32, clip="b"*32, job="c"*32, geometrySha256="d"*64,
        captureEpoch="9dbe1c39-9d2a-4d8c-93f8-12982d6f0202", beganAtMs=1000, endedAtMs=1400,
        width=64, height=48, frames=len(index_rows), durationTicks90k=index_rows[-1]["relative_ticks_90k"],
        videoBytes=len(video), endedEarly=None, stopReason="walk_manual_stop",
    )

    def seal():
        index_data = "".join(json.dumps(row)+"\n" for row in index_rows).encode()
        files[0].write_bytes(video)
        files[1].write_bytes(index_data)
        files[2].write_text(json.dumps(dict(meta, indexBytes=len(index_data), indexSha256=digest(index_data))))

    seal()
    return files, index_rows, meta, seal


def test_validates_whole_export_and_decodes_bounded_original_clock_prefix(exported):
    files, _, _, _ = exported
    capture = validate_diagnostic_video(*files)
    assert capture.video_sha256 == digest(files[0].read_bytes())
    assert capture.metadata_sha256 == digest(files[2].read_bytes())
    assert capture.geometry == (64, 48)
    assert len(capture.frames) == 8
    decoded = list(decoded_diagnostic_video(capture, max_seconds=.1))
    assert [frame.pts for _, frame in decoded] == [0, 3000, 6000, 9000]
    assert all((frame.width, frame.height) == capture.geometry for _, frame in decoded)


def test_rejects_broken_rtp_order_even_if_index_hash_is_recomputed(exported):
    files, rows, _, seal = exported
    rows[1]["rtp_timestamp"] = rows[0]["rtp_timestamp"]
    seal()
    with pytest.raises(ProtocolError, match="diagnostic_video_frame_clock"):
        validate_diagnostic_video(*files)


def test_checks_all_access_units_before_selecting_short_prefix(exported):
    files, _, _, _ = exported
    data = bytearray(files[0].read_bytes())
    data[-1] ^= 1
    files[0].write_bytes(data)
    with pytest.raises(ProtocolError, match="diagnostic_video_access_unit_hash"):
        validate_diagnostic_video(*files)


def test_refuses_decoded_dimensions_that_disagree_with_metadata(exported):
    files, _, meta, seal = exported
    meta["width"] = 80
    seal()
    capture = validate_diagnostic_video(*files)
    with pytest.raises(ProtocolError, match="diagnostic_video_decoded_binding"):
        list(decoded_diagnostic_video(capture))
