"""Validate browser-exported vehicle video and decode a bounded replay prefix."""

import hashlib
import re
from bisect import bisect_right
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from motor_worker.browser_teach import parse, read, regular, rows, sha
from motor_worker.policy import epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer
from motor_worker.teach_capture import MAX_UNIT, MIB, nal_types

_ID = re.compile(r"[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_META = {
    "schema", "runId", "clip", "job", "captureEpoch", "beganAtMs", "endedAtMs",
    "width", "height", "frames", "durationTicks90k", "videoBytes", "indexBytes",
    "indexSha256", "endedEarly", "stopReason",
}
_FRAME = {
    "index", "offset", "bytes", "rtp_timestamp", "relative_ticks_90k",
    "worker_observed_at_ms", "geometry_reported", "key", "seekable", "sha256",
}
_MAX_FRAMES = 108000
_MAX_TICKS = 1801 * 90000
_MAX_TIME = 2**53 - 1
_MAX_DECODE_FRAMES = 4096


def _matches(value, pattern):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


@dataclass(frozen=True)
class DiagnosticVideoCapture:
    video: Path
    frames: tuple[dict, ...]
    metadata: dict
    metadata_sha256: str
    video_sha256: str

    @property
    def geometry(self):
        return self.metadata["width"], self.metadata["height"]


def _units(path, frames, *, end_of_file):
    with regular(path).open("rb") as stream:
        for row in frames:
            data = stream.read(row["bytes"])
            if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                raise ProtocolError("diagnostic_video_access_unit_hash")
            types = set(nal_types(data))
            if (not types.intersection({1, 5})
                    or row["key"] != (5 in types)
                    or row["seekable"] != {5, 7, 8}.issubset(types)
                    or not row["geometry_reported"] and types.intersection({5, 7, 8})):
                raise ProtocolError("diagnostic_video_picture_headers")
            yield row, data
        if end_of_file and stream.read(1):
            raise ProtocolError("diagnostic_video_extra_bytes")


def validate_diagnostic_video(video_path, index_path, metadata_path):
    """Check the complete export without decoding or loading the video into memory."""
    raw_meta = read(Path(metadata_path), 2048)
    meta = parse(raw_meta, 2048)
    begin, end = meta.get("beganAtMs"), meta.get("endedAtMs")
    width, height = meta.get("width"), meta.get("height")
    if (not _META <= meta.keys() <= _META | {"geometrySha256"}
            or meta["schema"] != "sphere-vehicle-video-v1"
            or any(not _matches(meta[key], _ID) for key in ("runId", "clip", "job"))
            or not epoch_valid(meta["captureEpoch"])
            or meta.get("geometrySha256") is not None and not _matches(meta["geometrySha256"], _SHA256)
            or not finite(begin, 0, _MAX_TIME) or not finite(end, begin, _MAX_TIME)
            or not integer(width, 1, 8192) or not integer(height, 1, 8192)
            or ((width+15)//16) * ((height+15)//16) > 36864
            or not integer(meta["frames"], 1, _MAX_FRAMES)
            or not integer(meta["durationTicks90k"], 0, _MAX_TICKS)
            or not integer(meta["videoBytes"], 1, 512 * MIB)
            or not integer(meta["indexBytes"], 1, 48 * MIB)
            or not _matches(meta["indexSha256"], _SHA256)
            or any(value is not None and (not isinstance(value, str) or len(value) > 128)
                   for value in (meta["endedEarly"], meta["stopReason"]))):
        raise ProtocolError("diagnostic_video_metadata")
    raw_index = read(Path(index_path), 48 * MIB)
    if len(raw_index) != meta["indexBytes"] or sha(raw_index) != meta["indexSha256"]:
        raise ProtocolError("diagnostic_video_index_hash")
    frames = rows(raw_index, _MAX_FRAMES)
    if len(frames) != meta["frames"]:
        raise ProtocolError("diagnostic_video_index_count")
    offset, ticks, previous = 0, 0, None
    for index, row in enumerate(frames):
        if (row.keys() != _FRAME
                or not integer(row["index"], index, index)
                or not integer(row["offset"], offset, offset)
                or not integer(row["bytes"], 1, MAX_UNIT)
                or not integer(row["rtp_timestamp"], 0, 2**32-1)
                or not integer(row["relative_ticks_90k"], 0, _MAX_TICKS)
                or not finite(row["worker_observed_at_ms"], begin, end)
                or any(type(row[key]) is not bool for key in ("geometry_reported", "key", "seekable"))
                or not _matches(row["sha256"], _SHA256)):
            raise ProtocolError("diagnostic_video_frame_index")
        if previous is not None:
            delta = (row["rtp_timestamp"] - previous["rtp_timestamp"]) % 2**32
            if not 0 < delta <= 90000 or row["worker_observed_at_ms"] < previous["worker_observed_at_ms"]:
                raise ProtocolError("diagnostic_video_frame_clock")
            ticks += delta
        elif not row["seekable"] or not row["geometry_reported"]:
            raise ProtocolError("diagnostic_video_keyframe_required")
        if row["relative_ticks_90k"] != ticks:
            raise ProtocolError("diagnostic_video_frame_clock")
        offset += row["bytes"]
        previous = row
    video = regular(Path(video_path).absolute())
    if offset != meta["videoBytes"] or video.stat().st_size != offset or ticks != meta["durationTicks90k"]:
        raise ProtocolError("diagnostic_video_extent")
    digest = hashlib.sha256()
    for _, data in _units(video, frames, end_of_file=True):
        digest.update(data)
    return DiagnosticVideoCapture(video, frames, meta, sha(raw_meta), digest.hexdigest())


def decoded_diagnostic_video(capture, *, max_seconds=60.0):
    """Read up to the first 60 seconds at verified RTP timestamps, one frame at a time."""
    import av

    if not finite(max_seconds, .1, 60):
        raise ProtocolError("diagnostic_video_decode_budget")
    count = bisect_right(capture.frames, round(max_seconds * 90000),
                         key=lambda row: row["relative_ticks_90k"])
    if not 1 <= count <= _MAX_DECODE_FRAMES:
        raise ProtocolError("diagnostic_video_decode_budget")
    codec = av.CodecContext.create("h264", "r")
    codec.thread_count = 1
    codec.options = {"max_pixels": "9437184"}
    pending, decoded = {}, 0

    def bound(frame):
        nonlocal decoded
        row = pending.pop(frame.pts, None)
        if row is None or row["index"] != decoded or (frame.width, frame.height) != capture.geometry:
            raise ProtocolError("diagnostic_video_decoded_binding")
        decoded += 1
        return row, frame

    try:
        for row, data in _units(capture.video, capture.frames[:count], end_of_file=count == len(capture.frames)):
            packet = av.Packet(data)
            packet.pts = packet.dts = row["relative_ticks_90k"]
            packet.time_base = Fraction(1, 90000)
            pending[packet.pts] = row
            if len(pending) > 32:
                raise ProtocolError("diagnostic_video_decoder_pending_quota")
            for frame in codec.decode(packet):
                yield bound(frame)
        for frame in codec.decode(None):
            yield bound(frame)
    except av.FFmpegError:
        raise ProtocolError("diagnostic_video_decode_failed") from None
    if pending or decoded != count:
        raise ProtocolError("diagnostic_video_decoded_count")
