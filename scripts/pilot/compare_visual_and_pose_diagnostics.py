"""Join saved same-capture 2D and 3D diagnostics by original frame ID.

Reference-time proximity is offline-only evidence; it never supplies game
position, obstacle clearance, a projected route, or permission to move.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def compare(place, pose):
    if place.get("same_capture") is not True or pose.get("independent_pass") is not False:
        raise ValueError("cross_probe_scope_mismatch")
    if place.get("physical_actions") != 0 or pose.get("physical_actions") != 0:
        raise ValueError("cross_probe_scope_mismatch")
    by_id = {}
    for row in place["samples"]:
        key = row["source_index"]
        if type(key) is not int or key in by_id:
            raise ValueError("cross_probe_duplicate_frames")
        by_id[key] = row
    output = []
    seen = set()
    for row in pose["samples"]:
        key = row["source_index"]
        if type(key) is not int or key in seen:
            raise ValueError("cross_probe_duplicate_frames")
        seen.add(key)
        other = by_id.get(key)
        if other is None:
            continue
        if abs(other["seconds"] - row["seconds"]) > 0.001:
            raise ValueError("cross_probe_time_mismatch")
        matched = other["state"] == "matched"
        ref = other.get("reference_seconds")
        within = matched and isinstance(ref, (int, float)) and abs(ref - row["seconds"]) <= 1
        output.append(
            {
                "source_index": key,
                "seconds": row["seconds"],
                "pose_pnp": row["lightglue_pnp"],
                "pose_ambiguous": row["lightglue_ambiguous"],
                "pose_center_jump": row["center_pair_discontinuity"],
                "visual_state": other["state"],
                "visual_reference_seconds": ref,
                "same_recording_reference_within_1s": within,
            }
        )
    jumps = [row for row in output if row["pose_center_jump"] is True]
    return {
        "schema": "sphere-2d-3d-cross-diagnostic-v1",
        "samples": output,
        "pose_frames": len(pose["samples"]),
        "shared_frames": len(output),
        "visual_matched": sum(row["visual_state"] == "matched" for row in output),
        "shared_jumps": len(jumps),
        "jumps_visual_matched": sum(row["visual_state"] == "matched" for row in jumps),
        "jumps_visual_reference_within_1s": sum(
            row["same_recording_reference_within_1s"] for row in jumps
        ),
        "reference_time_is_offline_only": True,
        "report_source_binding": "same_capture_report_and_frame_ids_not_hash_bound",
        "metric_scale": None,
        "independent_pass": False,
        "physical_actions": 0,
        "execution_qualified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("place", "pose", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        raise FileExistsError(out)
    result = compare(
        json.loads(Path(a.place).read_text(encoding="utf-8")),
        json.loads(Path(a.pose).read_text(encoding="utf-8")),
    )
    write_json(out, result)
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}))


if __name__ == "__main__":
    main()
