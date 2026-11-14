"""Render an honest offline progress-vs-image-match status timeline."""

import argparse
import json
from pathlib import Path


def render(report_path: Path, output: Path):
    import cv2 as cv
    import numpy as np

    report = json.loads(report_path.read_text(encoding="utf-8"))
    route = report["samples"]
    visual = report["alternate_global"]["samples"]
    if (
        not route
        or len(route) != len(visual)
        or [r["frame"] for r in route] != [r["frame"] for r in visual]
        or output.exists()
    ):
        raise ValueError("comparison_input_or_output_invalid")
    image = np.full((340, 1400, 3), (25, 27, 34), dtype=np.uint8)
    white, grey = (245, 245, 245), (205, 210, 220)
    colors = {
        "tracking": (120, 205, 80),
        "matched": (120, 205, 80),
        "confirming": (54, 191, 243),
        "unknown": (91, 91, 232),
        "end_view": (190, 160, 80),
    }
    cv.putText(
        image,
        "fuflo228: SAME 40 recorded frames | OFFLINE, NO GAME CONTROL",
        (30, 42),
        cv.FONT_HERSHEY_SIMPLEX,
        0.7,
        white,
        2,
        cv.LINE_AA,
    )
    for y, label, rows in (
        (105, "Strict route checkpoint", route),
        (185, "Global image resemblance", visual),
    ):
        cv.putText(image, label, (30, y + 10), cv.FONT_HERSHEY_SIMPLEX, 0.55, white, 1, cv.LINE_AA)
        for i, row in enumerate(rows):
            x = 365 + i * 25
            cv.rectangle(image, (x, y - 12), (x + 20, y + 15), colors[row["state"]], -1)
        counts = format_states(rows)
        cv.putText(image, counts, (365, y + 42), cv.FONT_HERSHEY_SIMPLEX, 0.5, grey, 1, cv.LINE_AA)
    cv.putText(
        image,
        "Green: hypothesis confirmed   Amber: confirming   Red: unknown",
        (30, 270),
        cv.FONT_HERSHEY_SIMPLEX,
        0.55,
        white,
        1,
        cv.LINE_AA,
    )
    cv.putText(
        image,
        "Global resemblance is NOT a pose, next turn, collision check or arrival.",
        (30, 307),
        cv.FONT_HERSHEY_SIMPLEX,
        0.55,
        grey,
        1,
        cv.LINE_AA,
    )
    if not cv.imwrite(str(output), image):
        raise RuntimeError("comparison_render_failed")


def format_states(rows):
    from collections import Counter

    counts = Counter(r["state"] for r in rows)
    return "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.report, args.output)
