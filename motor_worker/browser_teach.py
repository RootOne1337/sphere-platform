"""Offline browser-teaching validation and full-resolution reconstruction inputs.

Never opens Sphere, a model, a browser or native input. This prepares images and
provenance, not camera poses, a mesh, a motor route or an execution qualification.
Original browser v1/v2 files are neither rewritten nor converted into fake poses.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import stat
import statistics
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from motor_worker.policy import epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer, message
from motor_worker.teach_capture import MAX_UNIT, MIB, nal_types


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ProtocolError("browser_teach_regular_file_required")
    return path


def read(path, maximum):
    with regular(path).open("rb") as file:
        data = file.read(maximum+1)
    if len(data) > maximum:
        raise ProtocolError("browser_teach_file_quota")
    return data


def parse(data, maximum):
    try:
        return message(data.decode("utf-8"), maximum, strict_numbers=True)
    except UnicodeError:
        raise ProtocolError("browser_teach_utf8_required") from None


def rows(data, maximum):
    result = []
    for line in io.BytesIO(data):
        if len(result) >= maximum:
            raise ProtocolError("browser_teach_row_quota")
        result.append(parse(line, 4096))
    return tuple(result)


@dataclass(frozen=True)
class BrowserCapture:
    root: Path
    manifest: dict
    frames: tuple[dict, ...]
    inputs: tuple[dict, ...]
    originals: dict[str, bytes]

    @property
    def geometry(self):
        return self.manifest["config"]["width"], self.manifest["config"]["height"]


def validate_browser(directory):
    root = Path(directory).absolute()
    if root.resolve(strict=True) != root or not root.is_dir():
        raise ProtocolError("browser_teach_resolved_directory_required")
    originals = {"manifest.json": read(root/"manifest.json", 65536)}
    manifest = parse(originals["manifest.json"], 65536)
    schema = manifest.get("schema")
    if (schema not in {"sphere-browser-teaching-v1", "sphere-browser-teaching-v2"}
            or manifest.get("complete") is not True or manifest.get("release_confirmed") is not True
            or manifest.get("failure") is not None
            or not isinstance(manifest.get("id"), str) or len(manifest["id"]) != 32
            or any(c not in "0123456789abcdef" for c in manifest["id"])):
        raise ProtocolError("browser_teach_incomplete_or_unsupported")
    config = manifest.get("config")
    if (type(config) is not dict or config.get("id") != manifest["id"]
            or not epoch_valid(config.get("device_id")) or not epoch_valid(config.get("capture_epoch"))
            or config.get("source") != "direct_webrtc_h264"
            or not integer(config.get("width"), 16, 4096) or not integer(config.get("height"), 16, 4096)
            or config["width"]*config["height"] > 8*1024**2):
        raise ProtocolError("browser_teach_capture_binding")
    start, end = manifest.get("started_at_ms"), manifest.get("finalized_at_ms")
    if not finite(start, 0, 2**53-1) or not finite(end, start, start+630000):
        raise ProtocolError("browser_teach_clock_range")
    originals["COMPLETE"] = read(root/"COMPLETE", 1024)
    marker = parse(originals["COMPLETE"], 1024)
    if marker != {"manifest_sha256": sha(originals["manifest.json"])}:
        raise ProtocolError("browser_teach_completion_hash")
    files = manifest.get("files")
    if type(files) is not dict or set(files) != {"video.h264", "frames.jsonl", "inputs.jsonl"}:
        raise ProtocolError("browser_teach_file_manifest")
    for name, maximum in (("frames.jsonl", 16*MIB), ("inputs.jsonl", 8*MIB)):
        data = originals[name] = read(root/name, maximum)
        entry = files[name]
        if type(entry) is not dict or entry.get("bytes") != len(data) or entry.get("sha256") != sha(data):
            raise ProtocolError("browser_teach_journal_hash")
    frame_limit, byte_limit = (36000, 2**31) if schema.endswith("v2") else (7200, 512*MIB)
    if (not integer(manifest.get("frames"), 1, frame_limit)
            or not integer(manifest.get("events"), 1, 40000)):
        raise ProtocolError("browser_teach_row_quota")
    frames = rows(originals["frames.jsonl"], frame_limit)
    inputs = rows(originals["inputs.jsonl"], 40000)
    if len(frames) != manifest["frames"] or len(inputs) != manifest["events"]:
        raise ProtocolError("browser_teach_row_count")
    offset, ticks, previous = 0, 0, None
    for index, row in enumerate(frames):
        if (row.get("index") != index or type(row.get("index")) is not int
                or row.get("offset") != offset or type(row.get("offset")) is not int
                or not integer(row.get("bytes"), 1, MAX_UNIT)
                or not integer(row.get("rtp_timestamp"), 0, 2**32-1)
                or not integer(row.get("relative_ticks_90k"), 0, 601*90000)
                or not finite(row.get("worker_observed_at_ms"), start, end)
                or type(row.get("key")) is not bool
                or type(row.get("sha256")) is not str or len(row["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in row["sha256"])
                or "seekable" in row and type(row["seekable"]) is not bool):
            raise ProtocolError("browser_teach_frame_index")
        if previous:
            delta = (row["rtp_timestamp"]-previous["rtp_timestamp"]) % 2**32
            if not 0 < delta <= 90000 or row["worker_observed_at_ms"] < previous["worker_observed_at_ms"]:
                raise ProtocolError("browser_teach_frame_clock_order")
            ticks += delta
        if row["relative_ticks_90k"] != ticks or not index and not row["key"]:
            raise ProtocolError("browser_teach_media_clock_or_start")
        offset += row["bytes"]
        previous = row
    video = files["video.h264"]
    if (type(video) is not dict or not integer(video.get("bytes"), 1, byte_limit)
            or video["bytes"] != offset or regular(root/"video.h264").stat().st_size != offset
            or "media_duration_ticks_90k" in manifest and manifest["media_duration_ticks_90k"] != ticks):
        raise ProtocolError("browser_teach_video_extent")
    capture = BrowserCapture(root, manifest, frames, inputs, originals)
    validate_browser_inputs(capture)
    return capture


def validate_browser_inputs(capture):
    width, height = capture.geometry
    start, end = (capture.manifest[key] for key in ("started_at_ms", "finalized_at_ms"))
    pending, held, last_sequence, native_at, previous_at, closed = None, {}, 0, 0, start, False
    current_gesture = 0
    for event in capture.inputs:
        at = event.get("at_ms")
        stage = event.get("stage")
        if closed or not finite(at, previous_at, end) or stage not in {"submitted", "receipt", "closed"}:
            raise ProtocolError("browser_teach_input_order")
        previous_at = at
        sequence, action, pointer, gesture = (event.get(key) for key in ("sequence", "action", "pointer_id", "gesture"))
        if not all(type(value) is int for value in (sequence, action, pointer, gesture)):
            raise ProtocolError("browser_teach_input_identity")
        if stage == "closed":
            cancelled = event.get("cancelled_pointers", [])
            native = event.get("device_uptime_ms")
            if (pending or (sequence, gesture, action, pointer) != (0, 0, 3, -1)
                    or event.get("outcome") != "closed" or type(cancelled) is not list
                    or any(not integer(value, 0, 2) for value in cancelled)
                    or len(set(cancelled)) != len(cancelled) or set(cancelled) != set(held)
                    or native is not None and not integer(native, native_at, 2**53-1)
                    or held and native is None):
                raise ProtocolError("browser_teach_release_unconfirmed")
            closed = True
            continue
        heartbeat = action == 4 and pointer == -1
        if (not integer(sequence, 1, 2**31-1) or not integer(gesture, 0, 2**31-1)
                or not heartbeat and (action not in {0, 1, 2} or not integer(pointer, 0, 2)
                    or not integer(event.get("x"), 0, width-1) or not integer(event.get("y"), 0, height-1))):
            raise ProtocolError("browser_teach_input_value")
        if stage == "submitted":
            if pending or sequence <= last_sequence:
                raise ProtocolError("browser_teach_input_sequence")
            if (heartbeat and gesture != (current_gesture if held else 0)
                    or not heartbeat and (gesture < 1 or (action == 0) == (pointer in held)
                        or action != 0 and held.get(pointer) != gesture
                        or action == 0 and held and gesture != current_gesture
                        or action == 0 and not held and gesture <= current_gesture)):
                raise ProtocolError("browser_teach_contact_edges")
            pending, last_sequence = event, sequence
        else:
            native = event.get("device_uptime_ms")
            if (not pending or any(event.get(key) != pending.get(key) for key in
                                   ("sequence", "gesture", "action", "pointer_id", "x", "y"))
                    or event.get("outcome") != ("alive" if heartbeat else "applied")
                    or not integer(native, native_at, 2**53-1)):
                raise ProtocolError("browser_teach_input_receipt")
            if action == 0:
                held[pointer] = gesture
                current_gesture = gesture
            elif action == 1:
                del held[pointer]
            pending, native_at = None, native
    if not closed or pending:
        raise ProtocolError("browser_teach_release_unconfirmed")


def browser_units(capture):
    """One <=2MiB access unit at a time; all media is checked, not only keyframes."""
    with regular(capture.root/"video.h264").open("rb") as file:
        for row in capture.frames:
            data = file.read(row["bytes"])
            if sha(data) != row["sha256"]:
                raise ProtocolError("browser_teach_access_unit_hash")
            types = set(nal_types(data))
            if (not {1, 5} & types or row["key"] != (5 in types)
                    or "seekable" in row and row["seekable"] != {5, 7, 8}.issubset(types)
                    or row["index"] == 0 and not {5, 7, 8}.issubset(types)):
                raise ProtocolError("browser_teach_picture_headers")
            yield row, data
        if file.read(1):
            raise ProtocolError("browser_teach_video_changed")


def decoded_browser(capture):
    import av
    codec = av.CodecContext.create("h264", "r")
    codec.thread_count = 1
    codec.options = {"max_pixels": "8388608"}
    pending, decoded = {}, 0

    def bound(frame):
        nonlocal decoded
        if (frame.width, frame.height) != capture.geometry or frame.pts not in pending:
            raise ProtocolError("browser_teach_decoded_binding")
        decoded += 1
        return pending.pop(frame.pts), frame

    try:
        for row, data in browser_units(capture):
            packet = av.Packet(data)
            packet.pts = packet.dts = row["relative_ticks_90k"]
            packet.time_base = Fraction(1, 90000)
            pending[packet.pts] = row
            if len(pending) > 32:
                raise ProtocolError("browser_teach_decoder_pending_quota")
            for frame in codec.decode(packet):
                yield bound(frame)
        for frame in codec.decode(None):
            yield bound(frame)
    except av.FFmpegError:
        raise ProtocolError("browser_teach_decode_failed") from None
    if pending or decoded != len(capture.frames):
        raise ProtocolError("browser_teach_decoded_count")


def inspect_browser(directory):
    capture = validate_browser(directory)
    decoded, repeated, previous_rgb, unique_rgb = 0, 0, None, set()
    for _, frame in decoded_browser(capture):
        rgb_hash = sha(frame.to_ndarray(format="rgb24").tobytes())
        repeated += rgb_hash == previous_rgb
        unique_rgb.add(rgb_hash)
        previous_rgb = rgb_hash
        decoded += 1
    ticks = capture.frames[-1]["relative_ticks_90k"]
    gaps = [(b["relative_ticks_90k"]-a["relative_ticks_90k"])/90
            for a, b in zip(capture.frames, capture.frames[1:])]
    # Media spacing is not Android capture age. No native-to-browser clock map
    # or engine camera/depth exists in this format, even if config claims one.
    target = capture.manifest["config"].get("target_fps")
    target = target if finite(target, 1, 240) else None
    spacing = dict(intervals=len(gaps), median_ms=statistics.median(gaps) if gaps else None,
                   p95_ms=sorted(gaps)[math.ceil(.95*len(gaps))-1] if gaps else None,
                   max_ms=max(gaps) if gaps else None,
                   gaps_over_200ms=sum(gap > 200 for gap in gaps),
                   gaps_over_500ms=sum(gap > 500 for gap in gaps))
    return dict(schema=capture.manifest["schema"], clip=capture.manifest["id"],
                frames=decoded, seconds=ticks/90000,
                media_fps=(decoded-1)*90000/ticks if ticks else 0,
                geometry=capture.geometry, complete_verified=True, input_release_verified=True,
                source_capture_clock_mapping_known=False, reconstruction_qualified=False,
                execution_qualified=False, source_manifest_sha256=sha(capture.originals["manifest.json"]),
                observability=dict(schema="sphere-capture-observability-v1", declared_target_fps=target,
                    media_spacing=spacing, unique_decoded_rgb=len(unique_rgb),
                    consecutive_identical_rgb=repeated, video_bytes=capture.manifest["files"]["video.h264"]["bytes"],
                    measured_depth=False, engine_camera_poses=False, calibrated_intrinsics=False,
                    metric_scale=None, capture_to_receive_latency_ms=None,
                    exact_rgb_repeats_are_not_a_disconnect_verdict=True))


def prepare_browser(directory, output, *, interval=1.0, max_images=256, max_bytes=1024*MIB,
                    excluded_indices=frozenset()):
    """Lossless PNG at captured size. Unknown cameras stay unknown, never identity poses."""
    if not finite(interval, .2, 10) or not integer(max_images, 2, 1000) or not integer(max_bytes, MIB, 2**31):
        raise ProtocolError("browser_teach_preparation_budget")
    capture = validate_browser(directory)
    if (type(excluded_indices) is not frozenset or len(excluded_indices) > 1000
            or any(not integer(i, 0, len(capture.frames)-1) for i in excluded_indices)
            or len(capture.frames)-len(excluded_indices) < 2):
        raise ProtocolError('browser_teach_invalid_heldout_indices')
    if len(capture.frames) < 2:
        raise ProtocolError("browser_teach_insufficient_source_views")
    output = Path(output)
    if not output.is_absolute() or output.parent.resolve(strict=True) != output.parent:
        raise ProtocolError("browser_teach_output_resolved_absolute_required")
    if output == capture.root or output.is_relative_to(capture.root):
        raise ProtocolError("browser_teach_output_inside_source")
    output.mkdir()  # Exclusive; a failed run stays unsealed for inspection.
    images = output/"images"
    images.mkdir()
    source = output/"source"
    source.mkdir()
    used = 0
    for name, data in capture.originals.items():
        used += len(data)
        if used > max_bytes:
            raise ProtocolError("browser_teach_preparation_byte_quota")
        with (source/name).open("xb") as file:
            file.write(data)
    selected, next_tick, last = [], 0, None

    def save(row, frame):
        nonlocal used
        if len(selected) >= max_images:
            raise ProtocolError("browser_teach_preparation_image_quota")
        name = f"{row['index']:08d}.png"
        path = images/name
        with path.open("xb") as file:
            class BudgetWriter:
                def write(self, data):
                    if file.tell()+len(data) > max_bytes-used:
                        raise ProtocolError("browser_teach_preparation_byte_quota")
                    return file.write(data)

                def flush(self):
                    file.flush()
            frame.to_image().save(BudgetWriter(), format="PNG")
        size = path.stat().st_size
        used += size
        if used > max_bytes:
            raise ProtocolError("browser_teach_preparation_byte_quota")
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        selected.append(dict(image="images/"+name, source_index=row["index"],
                             relative_ticks_90k=row["relative_ticks_90k"],
                             worker_observed_at_ms=row["worker_observed_at_ms"],
                             source_access_unit_sha256=row["sha256"], png_sha256=digest, bytes=size))

    for row, frame in decoded_browser(capture):
        if row['index'] in excluded_indices:
            continue
        last = row, frame
        if row["relative_ticks_90k"] >= next_tick:
            save(row, frame)
            next_tick = row["relative_ticks_90k"]+round(interval*90000)
    if last and selected[-1]["source_index"] != last[0]["index"]:
        save(*last)
    result = dict(schema="sphere-reconstruction-input-v1", clip=capture.manifest["id"],
                  source_manifest_sha256=sha(capture.originals["manifest.json"]),
                  geometry=list(capture.geometry), images=selected,
                  source_frames_verified=len(capture.frames), source_input_events_verified=len(capture.inputs),
                  selection="fixed_media_interval_plus_last_not_quality_or_pose_selection",
                  source_video_copied=False, source_capture_clock_mapping_known=False,
                  cameras=None, metric_scale=None, camera_body_transform=None,
                  reconstruction_qualified=False, execution_qualified=False,
                  masks_applied=False, prepared_bytes=used)
    if excluded_indices:
        result['excluded_source_indices'] = sorted(excluded_indices)
    raw = (json.dumps(result, indent=2, allow_nan=False)+"\n").encode()
    if used+len(raw)+65 > max_bytes:
        raise ProtocolError("browser_teach_preparation_byte_quota")
    with (output/"reconstruction-input.json").open("xb") as file:
        file.write(raw)
    with (output/"COMPLETE").open("xb") as file:
        file.write(sha(raw).encode()+b"\n")
    return dict(images=len(selected), source_frames=len(capture.frames), geometry=capture.geometry,
                prepared=True, reconstruction_qualified=False, execution_qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["inspect", "prepare"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument("--max-images", type=int, default=256)
    parser.add_argument("--max-mib", type=int, default=1024)
    args = parser.parse_args()
    try:
        if args.command == "inspect":
            result = inspect_browser(args.directory)
        else:
            if args.output is None:
                raise ProtocolError("browser_teach_output_required")
            from scripts.pilot.resource_guard import collect, evaluate
            if evaluate(collect(args.output.parent)):
                raise ProtocolError("browser_teach_resource_guard")
            result = prepare_browser(args.directory, args.output, interval=args.interval,
                                     max_images=args.max_images, max_bytes=args.max_mib*MIB)
        print(json.dumps(dict(success=True, **result)))
        return 0
    except (ProtocolError, OSError, UnicodeError, ImportError, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, ProtocolError) else "browser_teach_io_dependency_or_cancelled"
        print(json.dumps(dict(success=False, failure=reason)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
