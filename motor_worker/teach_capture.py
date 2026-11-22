"""Opt-in, bounded direct H264 dataset sink. No input or game authority.

Stores depacketized access units, RTP timing and sanitized local command/receipt
events. RTP and native uptime clocks remain separate. COMPLETE is the last commit
record; interrupted or overflowing recordings cannot be imported as complete.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from motor_worker.policy import epoch_valid, finite
from motor_worker.protocol import ProtocolError, VideoBinding, integer, message

MIB = 1024 * 1024
MAX_UNIT = 2 * MIB
FILES = ("video.h264", "frames.jsonl", "inputs.jsonl")


def encoded_json(data):
    return (json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n").encode()


def nal_types(data):
    if type(data) is not bytes or not 1 <= len(data) <= MAX_UNIT:
        raise ProtocolError("teach_access_unit_size")
    starts, i = [], 0
    # Scan in native bytes.find: a large IDR must not block the RTP event loop
    # with a Python iteration for every byte. Accept both AnnexB prefix lengths.
    while (at := data.find(b"\0\0\1", i)) >= 0:
        start = at-1 if at > 0 and data[at-1] == 0 else at
        header = at+3
        if header >= len(data) or len(starts) >= 64 or data[header] & 128:
            raise ProtocolError("teach_invalid_annexb")
        starts.append((start, data[header] & 31))
        i = header
    if not starts or starts[0][0] != 0 or any(t not in {1, 5, 6, 7, 8, 9} for _, t in starts):
        raise ProtocolError("teach_invalid_annexb")
    return tuple(t for _, t in starts)


@dataclass(frozen=True)
class TeachBudget:
    duration: float = 120
    bytes: int = 512 * MIB
    frames: int = 18000
    events: int = 40000

    def __post_init__(self):
        if (not finite(self.duration, 1, 300) or not integer(self.bytes, MIB, 2**31)
                or not integer(self.frames, 1, 36000) or not integer(self.events, 1, 80000)):
            raise ProtocolError("invalid_teach_budget")


class TeachCapture:
    """One owner calls bind/offer/finish. A bounded thread owns all file IO.

    offer() never waits for disk. Overflow aborts rather than silently dropping
    demonstrations. Only this new directory is used; no old data is removed.
    """

    def __init__(self, directory, *, device_id, episode_id, profile_revision,
                 budget=TeachBudget(), clock=time.perf_counter):
        if (not all(epoch_valid(v) for v in (device_id, episode_id, profile_revision))
                or type(budget) is not TeachBudget or not callable(clock)):
            raise ProtocolError("invalid_teach_identity")
        self.root = Path(directory)
        if not self.root.is_absolute() or self.root.parent.resolve(strict=True) != self.root.parent:
            raise ProtocolError("teach_path_must_be_resolved_absolute")
        self.root.mkdir()  # Exclusive creation; fixed relative filenames only.
        self.budget, self.clock = budget, clock
        self.identity = dict(device_id=device_id, episode_id=episode_id, profile_revision=profile_revision)
        self.binding = None
        self.started = clock()
        self.last_received = None
        self.first_rtp = self.last_rtp = None
        self.rtp_ticks = 0
        self.video_bytes = self.queued_bytes = self.reserved_bytes = 0
        self.frames = self.events = 0
        self.pending = {}
        self.native_held = False
        self.commands = self.applied = 0
        self.last_command = 0
        self.held_gesture = None
        self.last_event_at = self.last_native_at = None
        self.failure = None
        self.finished = False
        self.summary = None
        self._lock = threading.Lock()
        self._queue = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._write, name="sphere-teach-writer", daemon=True)
        self._thread.start()

    def bind(self, binding):
        if type(binding) is not VideoBinding:
            self.abort("teach_capture_geometry")
        elif self.binding is not None and self.binding != binding:
            self.abort("teach_capture_changed")
        elif not epoch_valid(binding.epoch) or not integer(binding.width, 16, 4096) or not integer(binding.height, 16, 4096):
            self.abort("teach_capture_geometry")
        else:
            self.binding = binding

    def abort(self, reason):
        if self.failure is None:
            self.failure = reason
        return False

    def _at(self, at):
        return (not self.finished and self.failure is None and self.binding is not None
                and finite(at, self.started, self.started + self.budget.duration + 15))

    def _enqueue(self, kind, data, metadata):
        size = len(data) + len(metadata)
        with self._lock:
            if self.failure or self.finished:
                return False
            if (self.queued_bytes + size > 8 * MIB
                    or self.reserved_bytes + size > self.budget.bytes):
                return self.abort("teach_byte_quota")
            try:
                self._queue.put_nowait((kind, data, metadata, size))
            except queue.Full:
                return self.abort("teach_writer_backpressure")
            self.queued_bytes += size
            self.reserved_bytes += size
        return True

    def offer_access_unit(self, data, timestamp, received_at):
        if not self._at(received_at):
            return self.abort("teach_access_unit_binding_or_time")
        if not integer(timestamp, 0, 2**32-1):
            return self.abort("teach_invalid_rtp_timestamp")
        try:
            types = nal_types(data)
        except ProtocolError as error:
            return self.abort(str(error))
        if 1 not in types and 5 not in types:
            return self.abort("teach_missing_picture")
        if self.first_rtp is None:
            if not {5, 7, 8}.issubset(types):
                return True  # Wait for a self-contained IDR; no delta-only file.
            self.first_rtp = timestamp
        elif self.last_received is None or received_at < self.last_received:
            return self.abort("teach_receiver_clock_order")
        if self.last_rtp is not None:
            delta = (timestamp - self.last_rtp) % (2**32)
            if not 0 < delta <= 90000:
                return self.abort("teach_rtp_discontinuity")
            self.rtp_ticks += delta
        if self.frames >= self.budget.frames or self.rtp_ticks > self.budget.duration * 90000:
            return self.abort("teach_frame_or_duration_quota")
        metadata = encoded_json(dict(sequence=self.frames+1, offset=self.video_bytes, size=len(data),
                                     rtp_ticks=self.rtp_ticks, received_at=received_at, keyframe=5 in types))
        if not self._enqueue("frame", data, metadata):
            return False
        self.last_received, self.last_rtp = received_at, timestamp
        self.frames += 1
        self.video_bytes += len(data)
        return True

    def command(self, data, at):
        """Only the owner's submitted pointer changes; never save tokens/owner/text."""
        if data.get("type") != "touch_event" or data.get("action") == 4:
            return True
        if (not self._at(at) or self.last_event_at is not None and at < self.last_event_at
                or data.keys() != {"type", "sequence", "gesture", "action", "x", "y"}
                or not integer(data["sequence"], 1, 2147483647)
                or not integer(data["gesture"], 1, 2147483647)
                or not integer(data["action"], 0, 3)
                or not integer(data["x"], 0, self.binding.width-1)
                or not integer(data["y"], 0, self.binding.height-1)
                or data["sequence"] <= self.last_command or self.pending
                or (data["action"] == 0) == self.native_held
                or data["action"] != 0 and data["gesture"] != self.held_gesture):
            return self.abort("teach_invalid_or_overlapping_input")
        if self.events >= self.budget.events:
            return self.abort("teach_event_quota")
        safe = {k: data[k] for k in ("sequence", "gesture", "action", "x", "y")}
        line = encoded_json(dict(kind="submitted", at=at, **safe))
        if not self._enqueue("input", b"", line):
            return False
        self.pending[data["sequence"]] = safe
        self.last_command = data["sequence"]
        self.last_event_at = at
        self.events += 1
        self.commands += 1
        return True

    def receipt(self, data, at):
        if (data.get("type") == "shared_input_status" and data.get("sequence") == 0
                and data.get("outcome") == "closed" and self.binding
                and data.get("capture_epoch") == self.binding.epoch):
            native = data.get("device_uptime_ms")
            if (not self._at(at) or not integer(native, 0, 2**53-1)
                    or self.last_event_at is not None and at < self.last_event_at
                    or self.last_native_at is not None and native < self.last_native_at):
                return self.abort("teach_invalid_close_receipt")
            if self.events >= self.budget.events:
                return self.abort("teach_event_quota")
            if not self._enqueue("input", b"", encoded_json(dict(kind="closed", at=at,
                                                               device_uptime_ms=data["device_uptime_ms"]))):
                return False
            self.native_held, self.held_gesture = False, None
            self.last_event_at, self.last_native_at = at, native
            self.events += 1
            return True
        if data.get("type") != "shared_input_status" or data.get("sequence") not in self.pending:
            return True
        expected = self.pending[data["sequence"]]
        if (not self._at(at) or data.get("capture_epoch") != self.binding.epoch
                or data.get("gesture") != expected["gesture"] or data.get("action") != expected["action"]
                or self.last_event_at is not None and at < self.last_event_at
                or not integer(data.get("device_uptime_ms"), 0, 2**53-1)
                or self.last_native_at is not None and data["device_uptime_ms"] < self.last_native_at
                or data.get("outcome") != "applied"):
            return self.abort("teach_input_not_confirmed")
        if self.events >= self.budget.events:
            return self.abort("teach_event_quota")
        line = encoded_json(dict(kind="applied", at=at, sequence=data["sequence"],
                                 device_uptime_ms=data["device_uptime_ms"]))
        if not self._enqueue("input", b"", line):
            return False
        del self.pending[data["sequence"]]
        self.native_held = expected["action"] in {0, 2}
        self.held_gesture = expected["gesture"] if self.native_held else None
        self.last_event_at, self.last_native_at = at, data["device_uptime_ms"]
        self.events += 1
        self.applied += 1
        return True

    def _write(self):
        handles = []
        try:
            for name in FILES:
                handles.append((self.root / name).open("xb"))
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    kind, data, metadata, size = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    if kind == "frame":
                        handles[0].write(data)
                        handles[1].write(metadata)
                    else:
                        handles[2].write(metadata)
                finally:
                    with self._lock:
                        self.queued_bytes -= size
            for handle in handles:
                handle.flush()
                os.fsync(handle.fileno())
        except (OSError, ValueError):
            self.abort("teach_writer_io")
        finally:
            for handle in handles:
                handle.close()

    def finish(self, *, transport_success, input_released, timeout=3):
        if self.summary is not None:
            return self.summary
        self.finished = True
        self._stop.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            self.abort("teach_writer_retirement_unknown")
        if not transport_success:
            self.abort("teach_transport_not_complete")
        if self.binding is None or not self.frames:
            self.abort("teach_no_video")
        if self.pending or self.native_held or self.commands and not input_released:
            self.abort("teach_input_release_unconfirmed")
        if self.failure is None:
            try:
                artifacts = {}
                for name in FILES:
                    p = self.root / name
                    with p.open("rb") as source:
                        artifacts[name] = dict(bytes=p.stat().st_size, sha256=hashlib.file_digest(source, "sha256").hexdigest())
                manifest = dict(schema_version=1, **self.identity, capture_epoch=self.binding.epoch,
                                width=self.binding.width, height=self.binding.height,
                                media_clock="rtp_90000_relative_origin", input_clock="android_uptime_ms",
                                event_clock="worker_perf_counter", started_at=self.started,
                                source_capture_clock_mapping_known=False, quality_qualified=False,
                                purpose="video_and_own_inputs" if self.commands else "video_only",
                                frame_count=self.frames, event_count=self.events, artifacts=artifacts)
                validate_inputs(self.root, manifest)
                payload = encoded_json(manifest)
                with (self.root / "manifest.json").open("xb") as dest:
                    dest.write(payload)
                    dest.flush()
                    os.fsync(dest.fileno())
                with (self.root / "COMPLETE").open("xb") as dest:
                    dest.write(hashlib.sha256(payload).hexdigest().encode() + b"\n")
                    dest.flush()
                    os.fsync(dest.fileno())
            except ProtocolError as error:
                self.abort(str(error))
            except OSError:
                self.abort("teach_finalize_io")
        self.summary = dict(complete=self.failure is None, failure=self.failure, frames=self.frames,
                            input_commands=self.commands, applied_inputs=self.applied,
                            writer_retired=not self._thread.is_alive(), native_clock_mapping_known=False,
                            physical_route_accepted=False)
        return self.summary


def validate_capture(directory):
    """Bounded, exact-file importer; no code, pickle, path traversal or playback."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ProtocolError("teach_capture_unavailable")
    expected = {*FILES, "manifest.json", "COMPLETE"}
    names = set()
    for p in root.iterdir():
        if p.name not in expected or p.is_symlink() or not p.is_file():
            raise ProtocolError("teach_capture_not_complete")
        names.add(p.name)
    if names != expected:
        raise ProtocolError("teach_capture_not_complete")
    with (root/"manifest.json").open("rb") as f:
        payload = f.read(16385)
    with (root/"COMPLETE").open("rb") as f:
        receipt = f.read(66)
    if len(payload) > 16384 or receipt != hashlib.sha256(payload).hexdigest().encode()+b"\n":
        raise ProtocolError("teach_manifest_integrity")
    try:
        manifest = message(payload.decode("utf-8"), 16384, strict_numbers=True)
    except UnicodeDecodeError:
        raise ProtocolError("teach_manifest_encoding") from None
    keys = {"schema_version", "device_id", "episode_id", "profile_revision", "capture_epoch", "width", "height",
            "media_clock", "input_clock", "event_clock", "started_at", "source_capture_clock_mapping_known",
            "quality_qualified", "purpose", "frame_count", "event_count", "artifacts"}
    if (manifest.keys() != keys or not integer(manifest["schema_version"], 1, 1)
            or not all(epoch_valid(manifest[k]) for k in ("device_id", "episode_id", "profile_revision", "capture_epoch"))
            or not integer(manifest["width"], 16, 4096) or not integer(manifest["height"], 16, 4096)
            or not integer(manifest["frame_count"], 1, 36000) or not integer(manifest["event_count"], 0, 80000)
            or manifest["source_capture_clock_mapping_known"] is not False or manifest["quality_qualified"] is not False
            or type(manifest["purpose"]) is not str or manifest["purpose"] not in {"video_only", "video_and_own_inputs"}
            or manifest["media_clock"] != "rtp_90000_relative_origin"
            or manifest["input_clock"] != "android_uptime_ms" or manifest["event_clock"] != "worker_perf_counter"
            or not finite(manifest["started_at"], 0, float("inf"))
            or type(manifest["artifacts"]) is not dict or manifest["artifacts"].keys() != set(FILES)):
        raise ProtocolError("teach_invalid_manifest")
    total = 0
    for name, artifact in manifest["artifacts"].items():
        if (type(artifact) is not dict or artifact.keys() != {"bytes", "sha256"}
                or not integer(artifact["bytes"], 0, 2**31)):
            raise ProtocolError("teach_invalid_artifact")
        total += artifact["bytes"]
        p = root/name
        if total > 2**31 or p.stat().st_size != artifact["bytes"]:
            raise ProtocolError("teach_artifact_quota_or_size")
        with p.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if artifact["sha256"] != digest:
            raise ProtocolError("teach_artifact_integrity")
    return manifest


def capture_units(directory, manifest):
    """Iterate bounded access units with their recorded clock; never live frames."""
    root = Path(directory)
    count = offset = 0
    ticks = received = None
    with (root/"frames.jsonl").open("rb") as index, (root/"video.h264").open("rb") as video:
        while line := index.readline(4097):
            if len(line) > 4096:
                raise ProtocolError("teach_frame_index_quota")
            data = message(line.decode("utf-8"), 4096, strict_numbers=True)
            if (data.keys() != {"sequence", "offset", "size", "rtp_ticks", "received_at", "keyframe"}
                    or not integer(data["sequence"], count+1, count+1)
                    or not integer(data["offset"], offset, offset)
                    or not integer(data["size"], 1, MAX_UNIT)
                    or not integer(data["rtp_ticks"], 0 if ticks is None else ticks+1, 300*90000)
                    or ticks is None and data["rtp_ticks"] != 0
                    or not finite(data["received_at"], manifest["started_at"], manifest["started_at"]+315)
                    or received is not None and data["received_at"] < received
                    or type(data["keyframe"]) is not bool or count >= manifest["frame_count"]):
                raise ProtocolError("teach_invalid_frame_index")
            payload = video.read(data["size"])
            if len(payload) != data["size"]:
                raise ProtocolError("teach_truncated_video")
            types = nal_types(payload)
            if data["keyframe"] != (5 in types) or count == 0 and not {5, 7, 8}.issubset(types):
                raise ProtocolError("teach_frame_index_codec_mismatch")
            count += 1
            offset += len(payload)
            ticks, received = data["rtp_ticks"], data["received_at"]
            yield data, payload
        if count != manifest["frame_count"] or video.read(1):
            raise ProtocolError("teach_frame_count_or_trailing_video")


def validate_inputs(directory, manifest):
    """Check journal structure and submission→receipt edges in separate clocks."""
    pending = held = None
    last_sequence = count = commands = applied = 0
    last_at = last_native = None
    with (Path(directory)/"inputs.jsonl").open("rb") as source:
        while line := source.readline(4097):
            if len(line) > 4096 or count >= manifest["event_count"]:
                raise ProtocolError("teach_input_index_quota")
            data = message(line.decode("utf-8"), 4096, strict_numbers=True)
            kind, at = data.get("kind"), data.get("at")
            if type(kind) is not str:
                raise ProtocolError("teach_input_kind_invalid")
            if (not finite(at, manifest["started_at"], manifest["started_at"]+315)
                    or last_at is not None and at < last_at):
                raise ProtocolError("teach_input_clock_order")
            last_at, count = at, count+1
            if kind == "submitted":
                if (data.keys() != {"kind", "at", "sequence", "gesture", "action", "x", "y"}
                        or pending or not integer(data["sequence"], last_sequence+1, 2147483647)
                        or not integer(data["gesture"], 1, 2147483647) or not integer(data["action"], 0, 3)
                        or not integer(data["x"], 0, manifest["width"]-1)
                        or not integer(data["y"], 0, manifest["height"]-1)
                        or (data["action"] == 0) == (held is not None)
                        or data["action"] != 0 and data["gesture"] != held):
                    raise ProtocolError("teach_input_edges_invalid")
                pending, last_sequence = data, data["sequence"]
                commands += 1
            elif kind in {"applied", "closed"}:
                expected = {"kind", "at", "device_uptime_ms"} | ({"sequence"} if kind == "applied" else set())
                native = data.get("device_uptime_ms")
                if (data.keys() != expected or not integer(native, 0, 2**53-1)
                        or last_native is not None and native < last_native):
                    raise ProtocolError("teach_native_input_clock_order")
                last_native = native
                if kind == "applied":
                    if (not pending or not integer(data["sequence"], 1, 2147483647)
                            or data["sequence"] != pending["sequence"]):
                        raise ProtocolError("teach_receipt_without_submission")
                    held = pending["gesture"] if pending["action"] in {0, 2} else None
                    pending = None
                    applied += 1
                else:
                    held = None
            else:
                raise ProtocolError("teach_input_kind_invalid")
    if (count != manifest["event_count"] or pending or held is not None
            or (commands > 0) != (manifest["purpose"] == "video_and_own_inputs")):
        raise ProtocolError("teach_unresolved_input_journal")
    return dict(commands=commands, applied=applied, complete=True)
