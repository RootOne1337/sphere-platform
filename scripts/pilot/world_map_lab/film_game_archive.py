"""Overlay measured image localization on every frame of an existing game recording."""

import argparse
import hashlib
import json
import math
import subprocess
from bisect import bisect_right
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import av
import numpy as np
from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageDraw, ImageOps

from scripts.pilot.world_map_lab.report_first_person import (
    BG,
    BLUE,
    DIM,
    FG,
    GREEN,
    ORANGE,
    PANEL,
    label,
)


def film(source, observations, output):
    report = json.loads(observations.read_bytes())
    video = source / "video.h264"
    with video.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != report["videoSha256"]:
            raise ValueError("observations refer to another game recording")
    table = [json.loads(line) for line in (source / "frames.jsonl").read_bytes().splitlines()]
    ticks = [r["relative_ticks_90k"] for r in table]
    if (
        ticks[0] != 0
        or any(b <= a for a, b in zip(ticks, ticks[1:]))
        or len(ticks) != report["decoded"]
    ):
        raise ValueError("invalid source frame clock")
    rows = report["rows"]
    if (
        not rows
        or any(a["frame"] >= b["frame"] for a, b in zip(rows, rows[1:]))
        or any(
            not 0 <= r["frame"] < len(ticks)
            or abs(r["capture_s"] - ticks[r["frame"]] / 90000) > 0.001
            for r in rows
        )
    ):
        raise ValueError("localization timestamps differ from source frames")
    seconds = ticks[-1] / 90000
    frame_ids = [r["frame"] for r in rows]
    valid = [r for r in rows if r.get("xyz") is not None]
    if not valid:
        raise ValueError("no camera poses in this archive")
    points = np.asarray([r["xyz"][:2] for r in valid])
    c = (points.max(axis=0) + points.min(axis=0)) / 2
    scale = min(355 / max(1, np.ptp(points[:, 0])), 198 / max(1, np.ptp(points[:, 1])))

    def xy(r):
        x, y = (np.asarray(r["xyz"][:2]) - c) * scale
        return 1443 + x, 267 - y

    traces = []
    for j, (key, title, unit, color) in enumerate(
        [
            ("supports", "Опоры совпадения", "точек", GREEN),
            ("lateral", "До линии маршрута", "ед.", BLUE),
            ("ms", "Поиск по кадру", "мс", ORANGE),
        ]
    ):
        cap = max(1, math.ceil(max(r.get(key, 0) or 0 for r in rows)))
        x = 32 + j * 546
        coords = [
            None
            if r.get(key) is None
            else (x + 483 * r["capture_s"] / seconds, 837 - 78 * r[key] / cap)
            for r in rows
        ]
        traces.append((key, title, unit, color, x, cap, coords))
    template = Image.new("RGB", (1708, 960), BG)
    d = ImageDraw.Draw(template)
    label(d, (28, 15), "SPHERE LAB   /   BLACK RUSSIA", 16, BLUE, True)
    label(d, (28, 39), "Scooter 4  ·  исходная запись игры", 32, FG, True)
    label(d, (1210, 42), "Локализация по карте Ariane", 20, DIM)
    d.rounded_rectangle((1228, 96, 1682, 708), 12, fill=PANEL)
    label(d, (1252, 115), "Оценки положения", 23, FG, True)
    for k in range(5):
        x = 1252 + 96 * k
        d.line((x, 166, x, 382), fill="#294353")
        y = 166 + 54 * k
        d.line((1252, y, 1650, y), fill="#294353")
    label(d, (1252, 406), "Разрывы соответствуют потере позы", 16, DIM)
    label(d, (1252, 478), "Сопоставление с картой", 17, DIM)
    label(d, (1252, 588), "С последней найденной позы", 17, DIM)
    for key, title, unit, color, x, cap, coords in traces:
        label(d, (x, 719), title, 22, FG, True)
        for h in (759, 798, 837):
            d.line((x, h, x + 483, h), fill="#2c4252")
        label(d, (x, 846), "0 с", 15, DIM)
        label(d, (x + 414, 846), f"{seconds:.1f} с", 15, DIM)
        label(d, (x + 394, 718), f"{cap} {unit}", 14, DIM)
    label(
        d,
        (28, 902),
        "Без HUD  ·  исходные метки времени RTP  ·  графики получены при обработке записи",
        18,
        DIM,
    )

    def panel(frame, i):
        img = template.copy()
        brush = ImageDraw.Draw(img)
        pic = ImageOps.contain(frame.to_image(), (1178, 610), Image.Resampling.LANCZOS)
        img.paste(pic, (24 + (1178 - pic.width) // 2, 96 + (610 - pic.height) // 2))
        t = ticks[i] / 90000
        idx = bisect_right(frame_ids, i) - 1
        current = rows[idx] if idx >= 0 else {}
        active = current.get("xyz") is not None
        label(
            brush,
            (1260, 510),
            "Найден кандидат" if active else "Позиция потеряна",
            24,
            GREEN if active else ORANGE,
            True,
        )
        latest = None
        for n in range(idx + 1):
            r = rows[n]
            if r.get("xyz") is None:
                continue
            point = xy(r)
            if n > 0 and rows[n - 1].get("xyz") is not None:
                brush.line([xy(rows[n - 1]), point], fill=GREEN, width=3)
            else:
                brush.ellipse((point[0] - 2, point[1] - 2, point[0] + 2, point[1] + 2), fill=GREEN)
            latest = r
        if active:
            x, y = xy(current)
            brush.ellipse((x - 5, y - 5, x + 5, y + 5), fill=FG, outline=BG, width=2)
        label(
            brush, (1252, 619), f"{t - latest['capture_s']:.2f} с" if latest else "—", 26, FG, True
        )
        label(brush, (1252, 662), f"Игровой кадр  {i + 1} / {len(ticks)}", 16, DIM)
        for key, title, unit, color, x, cap, coords in traces:
            for j in range(1, idx + 1):
                if coords[j - 1] and coords[j]:
                    brush.line([coords[j - 1], coords[j]], fill=color, width=3)
            cursor = x + 483 * t / seconds
            brush.line((cursor, 759, cursor, 837), fill="#839aa8", width=1)
            if current.get(key) is not None:
                label(
                    brush,
                    (x + 240, 719),
                    f"{current[key]:.1f}" if key == "lateral" else str(round(current[key])),
                    17,
                    color,
                    True,
                )
        label(brush, (1535, 902), f"{t:05.2f} с", 20, FG)
        return img

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as tmpdir:
        tmp = Path(tmpdir)
        with av.open(str(video), format="h264") as src, av.open(str(tmp / "v.mp4"), "w") as dest:
            stream = dest.add_stream("libx264", rate=30)
            stream.width, stream.height = template.size
            stream.pix_fmt = "yuv420p"
            stream.codec_context.time_base = Fraction(1, 90000)
            stream.codec_context.max_b_frames = 0
            stream.options = {"crf": "18", "preset": "veryfast"}
            count = 0
            for i, frame in enumerate(src.decode(video=0)):
                out = av.VideoFrame.from_image(panel(frame, i))
                out.pts = ticks[i]
                out.time_base = Fraction(1, 90000)
                for packet in stream.encode(out):
                    dest.mux(packet)
                count += 1
            for packet in stream.encode():
                dest.mux(packet)
        if count != len(ticks):
            raise ValueError("frame count mismatch")
        movie = tmp / "report.mp4"
        subprocess.run(
            [
                get_ffmpeg_exe(),
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(tmp / "v.mp4"),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                "-movflags",
                "+faststart",
                str(movie),
            ],
            check=True,
        )
        with av.open(str(movie)) as final:
            clock = [f.pts * f.time_base for f in final.decode(video=0)]
        if len(clock) != len(ticks) or any(
            abs(float(t) - v / 90000) > 0.0001 for t, v in zip(clock, ticks, strict=True)
        ):
            raise ValueError("export altered source timestamps")
        movie.replace(output)
    with output.open("rb") as stream:
        receipt = dict(
            mode="archived_game_observation",
            sourceSha256=report["videoSha256"],
            observationsSha256=hashlib.sha256(observations.read_bytes()).hexdigest(),
            frameClockSha256=hashlib.sha256((source / "frames.jsonl").read_bytes()).hexdigest(),
            movieSha256=hashlib.file_digest(stream, "sha256").hexdigest(),
            frames=count,
            seconds=seconds,
            sampled=len(rows),
            located=len(valid),
        )
    metadata = output.with_suffix(".json")
    temp = metadata.with_suffix(".json.tmp")
    temp.write_text(json.dumps(receipt, allow_nan=False), encoding="utf8")
    temp.replace(metadata)
    print(f"{count} original game frames, {seconds:.3f} seconds, {len(rows)} measurements")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("source", "observations", "output"):
        cli.add_argument("--" + key, type=Path, required=True)
    args = cli.parse_args()
    film(args.source, args.observations, args.output)
