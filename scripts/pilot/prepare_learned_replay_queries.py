"""Export bounded, provenance-bound JPEG query frames from browser captures.

Run with the motor-worker virtualenv. This does not alter captures or run models.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from fractions import Fraction
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--capture", nargs=2, action="append", required=True, metavar=("LABEL", "PATH")
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--hz", default="5", help="sampling frequency, > 0 and <= 10")
    args = parser.parse_args()
    try:
        hz = Fraction(args.hz)
    except (ValueError, ZeroDivisionError):
        parser.error("invalid --hz")
    if not 0 < hz <= 10 or len(args.capture) > 10:
        parser.error("require 0 < --hz <= 10 and at most 10 captures")
    labels = [item[0] for item in args.capture]
    if len(set(labels)) != len(labels) or any(
        not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", x) for x in labels
    ):
        parser.error("labels must be unique and contain only letters, digits, _ or -")
    output = args.output.resolve()
    captures = []
    for label, source in args.capture:
        root = Path(source).resolve(strict=True)
        if output == root or root in output.parents or output in root.parents:
            parser.error("output and capture paths must not contain one another")
        capture = validate_browser(root)
        if capture.geometry[0] * 540 != capture.geometry[1] * 960:
            parser.error(f"{label}: expected 16:9 capture")
        captures.append((label, capture))
    import cv2 as cv

    cv.setNumThreads(2)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": "sphere-learned-replay-queries-v1",
        "hz": float(hz),
        "jpeg": {"width": 960, "height": 540, "quality": 86},
        "captures": [],
    }
    for label, capture in captures:
        video_hash = hashlib.sha256()
        with (capture.root / "video.h264").open("rb") as video:
            for chunk in iter(lambda: video.read(1024 * 1024), b""):
                video_hash.update(chunk)
        target = output / label
        target.mkdir()
        item = {
            "label": label,
            "capture_id": capture.manifest["id"],
            "manifest_sha256": hashlib.sha256(capture.originals["manifest.json"]).hexdigest(),
            "video_sha256": video_hash.hexdigest(),
            "frames": [],
        }
        next_slot = 0
        for row, decoded in decoded_browser(capture):
            ticks = row["relative_ticks_90k"]
            if ticks * hz.numerator < next_slot * 90000 * hz.denominator:
                continue
            # Skip elapsed slots without duplicating a source frame.
            next_slot = (ticks * hz.numerator) // (90000 * hz.denominator) + 1
            rgb = decoded.to_ndarray(format="rgb24")
            rgb = cv.resize(rgb, (960, 540), interpolation=cv.INTER_AREA)
            ok, encoded = cv.imencode(
                ".jpg", cv.cvtColor(rgb, cv.COLOR_RGB2BGR), [cv.IMWRITE_JPEG_QUALITY, 86]
            )
            if not ok or len(encoded) > 384 * 1024:
                raise ValueError("JPEG encode failed or exceeded 384 KiB")
            data = encoded.tobytes()
            relative = f"{label}/{row['index']:06d}.jpg"
            (output / relative).write_bytes(data)
            item["frames"].append(
                {
                    "frame_index": row["index"],
                    "rtp_timestamp": row["rtp_timestamp"],
                    "relative_ticks_90k": ticks,
                    "filename": relative,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest["captures"].append(item)
        print(f"{label}: {len(item['frames'])} frames", flush=True)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
