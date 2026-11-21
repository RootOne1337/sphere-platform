"""Render selected real frames from two captures, with verified report binding."""

import hashlib
import json
from pathlib import Path

import av
from PIL import Image, ImageDraw, ImageFont


def sha(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def frames(path, indices):
    values = {}
    with av.open(str(path)) as video:
        for index, frame in enumerate(video.decode(video=0)):
            if index in indices:
                values[index] = frame.to_image()
            if len(values) == len(indices):
                break
    if set(values) != set(indices):
        raise ValueError("frame_missing")
    return values


def render(report_path, prior_path, ref, query, output, *, targets=(8.0, 9.0, 10.0)):
    if output.exists():
        raise ValueError("output_exists")
    report, prior = (json.loads(p.read_text("utf-8")) for p in (report_path, prior_path))
    if (
        report["source_sha256"]["reference"] != sha(ref / "video.h264")
        or report["source_sha256"]["query"] != sha(query / "video.h264")
        or prior["source_sha256"] != report["source_sha256"]["reference"]
        or report["distinct_recordings"] is not True
        or report["physical_actions"] != 0
    ):
        raise ValueError("source_binding_changed")
    samples = report["results"]["ranked"]["samples"]
    selected = []
    for target in targets:
        row = min(
            (r for r in samples if r["state"] == "hypothesis"),
            key=lambda r: abs(r["seconds"] - target),
        )
        if abs(row["seconds"] - target) > 0.1:
            raise ValueError("expected_sample_missing")
        selected.append(row)
    ref_ids = [prior["reference_frames"][row["reference"]] for row in selected]
    qa = frames(query / "video.h264", {row["frame"] for row in selected})
    rb = frames(ref / "video.h264", set(ref_ids))
    image = Image.new("RGB", (1440, 1000), "#091321")
    draw = ImageDraw.Draw(image)

    def font(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", n)

    def bold(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", n)

    draw.text(
        (48, 24), "Два прохода: кадр запроса и найденный ракурс", font=bold(34), fill="#eff5ff"
    )
    draw.text(
        (48, 73),
        "Слева test1488 · справа сохранённый вид test228; времена каждой записи независимы.",
        font=font(18),
        fill="#a8bad1",
    )
    for i, (row, ref_id) in enumerate(zip(selected, ref_ids, strict=True)):
        y = 115 + i * 265
        for x, frame in ((48, qa[row["frame"]]), (732, rb[ref_id])):
            frame.thumbnail((660, 230), Image.Resampling.LANCZOS)
            image.paste(frame, (x, y))
        draw.text(
            (48, y + 232), f"test1488 · {row['seconds']:.2f} с", font=font(17), fill="#d9e6f5"
        )
        draw.text(
            (732, y + 232),
            f"test228 · {prior['reference_times'][row['reference']]:.2f} с · гипотеза",
            font=font(17),
            fill="#d9e6f5",
        )
    draw.text(
        (48, 925),
        "Похожесть отдельных видов видна; точные координаты, коррекция руля и весь маршрут не размечены.",
        font=font(18),
        fill="#f5d7a1",
    )
    image.save(output)


if __name__ == "__main__":
    import argparse

    root = Path(".local-pilot")
    base = root / "test228-merge-attempt-20261027"
    parser = argparse.ArgumentParser()
    parser.add_argument("--later", action="store_true")
    args = parser.parse_args()
    render(
        base
        / (
            "place-test1488-cross-session-later-v1"
            if args.later
            else "place-test1488-cross-session-v1"
        )
        / "report.json",
        base / "test228-place-multicandidate-diverse-v1/report.json",
        root / "reconstruction-jobs/b7bce94214db48e195dea1a2ac65faf2/input",
        root / "reconstruction-jobs/4fb278ec735145a5872cf7fd44d1ed9b/input",
        base / ("cross-session-later-pairs-v1.png" if args.later else "cross-session-pairs-v1.png"),
        targets=(14.0, 15.0, 15.8) if args.later else (8.0, 9.0, 10.0),
    )
