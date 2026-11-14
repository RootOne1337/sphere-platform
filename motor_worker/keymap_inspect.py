"""Bounded read-only LDPlayer metadata inspection, never a macro interpreter.

No reference file is followed, no layout is installed, no input is sent. The
observed fixed-point coordinates and VK codes require live HUD calibration
before a separately qualified Sphere keymapper may use them.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from motor_worker.protocol import ProtocolError, integer, message

LIMIT = 256 * 1024


def _point(value):
    if (type(value) is not dict or not {"x", "y"}.issubset(value)
            or not all(integer(value[k], 0, 10000) for k in ("x", "y"))):
        raise ProtocolError("keymap_point_outside_observed_domain")
    return {k: value[k] for k in ("x", "y")}


def _key(value, *, optional=False):
    if not integer(value, 0 if optional else 1, 255):
        raise ProtocolError("keymap_keycode_invalid")
    return value


def inspect_text(raw):
    data = message(raw, LIMIT, strict_numbers=True)
    result = dict(kind="READ_ONLY_LDPLAYER_INSPECTION_NOT_EXECUTABLE", executable=False,
                  input_sent=False, coordinate_model="OBSERVED_0_TO10000_REQUIRES_CALIBRATION",
                  native_multitouch_supported_by_inspector=False)
    if "keyboardMappings" not in data:
        references = data.get("resolutionRelatives")
        if type(references) is not dict or len(references) > 32:
            raise ProtocolError("keymap_reference_metadata_invalid")
        entries = []
        for resolution, ref in references.items():
            match = re.fullmatch(r"([1-9][0-9]{0,3})x([1-9][0-9]{0,3})", resolution)
            if (match is None or type(ref) is not dict
                    or ref.keys() != {"keyboardId", "joystickId"}):
                raise ProtocolError("keymap_reference_metadata_invalid")
            width, height = map(int, match.groups())
            if not all(16 <= v <= 8192 for v in (width, height)):
                raise ProtocolError("keymap_geometry_invalid")
            for value in ref.values():
                if (type(value) is not str or len(value) > 128
                        or value and (not value.endswith(".kmp") or any(c in value for c in '/\\:')
                                      or ".." in value or any(ord(c) < 32 for c in value))):
                    raise ProtocolError("keymap_reference_not_basename")
            entries.append(dict(width=width, height=height, **ref))
        return result | dict(format="smp_references_only", references=entries, references_followed=False)
    mappings, info = data["keyboardMappings"], data.get("configInfo")
    if (type(mappings) is not list or len(mappings) > 128 or type(info) is not dict
            or type(info.get("resolutionPattern")) is not dict):
        raise ProtocolError("keymap_mapping_or_geometry_invalid")
    resolution = info["resolutionPattern"]
    if not all(integer(resolution.get(k), 16, 8192) for k in ("width", "height")):
        raise ProtocolError("keymap_geometry_invalid")
    counts, rows, unsupported = Counter(), [], 0
    for mapping in mappings:
        if (type(mapping) is not dict or mapping.keys() != {"class", "data"}
                or type(mapping["class"]) is not str or not 1 <= len(mapping["class"]) <= 80
                or type(mapping["data"]) is not dict or len(mapping["data"]) > 64):
            raise ProtocolError("keymap_mapping_invalid")
        kind, fields = mapping["class"], mapping["data"]
        counts[kind] += 1
        row = dict(type=kind, executable=False)
        if kind == "ClassKeyboardDisc":
            row.update(origin=_point(fields.get("origin")), radius=fields.get("radius"),
                       keys={k: _key(fields.get(k)) for k in ("leftKey", "upKey", "rightKey", "downKey")})
            if not integer(row["radius"], 1, 10000) or len(set(row["keys"].values())) != 4:
                raise ProtocolError("keymap_disc_invalid")
            row["radius_unit_verified"] = False
        elif kind == "ClassKeyboardCurve":
            curve = fields.get("curve")
            if type(curve) is not list or not 2 <= len(curve) <= 1024:
                raise ProtocolError("keymap_curve_invalid")
            points, previous = [], 0
            for point in curve:
                xy = _point(point)
                timing = point.get("timing")
                if not integer(timing, previous, 60000) or len(points) == 0 and timing != 0:
                    raise ProtocolError("keymap_curve_timing_invalid")
                points.append(xy | dict(timing=timing))
                previous = timing
            row.update(key=_key(fields.get("key")), secondKey=_key(fields.get("secondKey", 0), optional=True),
                       points=points, timing_unit_verified=False)
        elif kind == "ClassMouseDrag":
            row.update(key=_key(fields.get("key")), origin=_point(fields.get("origin")),
                       sensitivity_unit_verified=False)
        elif kind == "ClassMouseTrigger":
            row["point"] = _point(fields.get("point"))
        elif kind == "ClassKeyboardMacros":
            script = fields.get("macros")
            if type(script) is not str or len(script.encode()) > 16384:
                raise ProtocolError("keymap_macro_quota")
            # Deliberately omit text, cursor paths and command interpretation.
            row.update(key=_key(fields.get("key")), script_bytes=len(script.encode()),
                       script_sha256=hashlib.sha256(script.encode()).hexdigest(), imported=False)
            unsupported += 1
        else:
            unsupported += 1  # Unknown kinds remain data, never implicit support.
            row["recognized"] = False
        rows.append(row)
    return result | dict(format="kmp", source_geometry={k: resolution[k] for k in ("width", "height")},
                         mappings=len(rows), classes=dict(counts), bindings=rows,
                         opaque_bindings=unsupported, complete_for_execution=False)


def inspect_file(path):
    source = Path(path)
    with source.open("rb") as handle:
        payload = handle.read(LIMIT+1)
    if len(payload) > LIMIT:
        raise ProtocolError("keymap_file_quota")
    try:
        report = inspect_text(payload.decode("utf-8-sig"))
    except UnicodeError:
        raise ProtocolError("keymap_file_encoding") from None
    return report | dict(source_bytes=len(payload), source_sha256=hashlib.sha256(payload).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = inspect_file(args.file)
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as dest:
                dest.write(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
        else:
            print(json.dumps(report, ensure_ascii=False))
        return 0
    except (ProtocolError, OSError) as error:
        print(json.dumps(dict(success=False, failure=str(error) if isinstance(error, ProtocolError) else "keymap_io")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
