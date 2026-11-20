"""Render a synchronized local first-person acceptance film and game/map comparison."""

import argparse
import json
import math
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BG = "#0a1420"
PANEL = "#112333"
FG = "#edf5f6"
DIM = "#a1b8ca"
BLUE = "#41cde4"
GREEN = "#68e6ab"
ORANGE = "#ffb074"


@lru_cache(maxsize=16)
def font(size, bold=False):
    options = ["segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold else ["segoeui.ttf", "DejaVuSans.ttf"]
    for name in options:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise RuntimeError("a Cyrillic typeface is required")


def label(draw, xy, msg, size=20, color=FG, bold=False):
    draw.text(xy, msg, font=font(size, bold), fill=color, stroke_width=0)


def comparisons(folder, result):
    checks = json.loads((folder / result).read_bytes())
    # Pick the nearest and the furthest camera relative to the driving corridor.
    examples = [min(checks, key=lambda v: v["lateral"]), max(checks, key=lambda v: v["lateral"])]
    out = Image.new("RGB", (1440, 1010), BG)
    draw = ImageDraw.Draw(out)
    label(draw, (30, 15), "SPHERE LAB   /   BLACK RUSSIA", 17, BLUE, True)
    label(draw, (30, 40), "Кадр игры и вид из той же расчётной позиции", 32, FG, True)
    label(draw, (30, 98), "Запись Scooter 4 · без HUD", 21, DIM)
    label(draw, (735, 98), "Карта Ariane · независимый рендер", 21, DIM)
    for index, case in enumerate(examples):
        y = 137 + index * 429
        i = case["frame"]
        for x, key in [(30, "game"), (735, "pose")]:
            with Image.open(folder / f"{key}-{i:03d}.jpg") as img:
                out.paste(img.resize((678, 381), Image.Resampling.LANCZOS), (x, y))
        desc = f"Кадр {i}     ·     до линии маршрута {case['lateral']:.2f} ед.     ·     место по совпадению контуров {case['rank']} из 7"
        label(draw, (31, y + 386), desc, 19, GREEN)
    out.save(folder / "game-map-comparison.png", optimize=True)


def plot(draw, rect, rows, index, total, key, cap, color):
    x, y, w, h = rect
    for step in range(3):
        yy = y + step * h / 2
        draw.line([(x, yy), (x + w, yy)], fill="#294152")
    points = [
        (x + w * i / max(total - 1, 1), y + h * (1 - np.clip(r[key] / cap, 0, 1)))
        for i, r in enumerate(rows[: index + 1])
    ]
    if len(points) > 1:
        draw.line(points, fill=color, width=3)


def film(folder, name, routefile):
    report = json.loads((folder / (name + ".json")).read_bytes())
    rows = report["observations"]
    route = np.array(json.loads(routefile.read_bytes())["trace"])
    pixels = route[:, :2] * [1, -1]
    extent = np.ptp(pixels, axis=0)
    scale = min(354 / max(extent[0], 1), 200 / max(extent[1], 1))
    middle = (pixels.max(axis=0) + pixels.min(axis=0)) / 2

    def project(xy):
        return tuple((np.asarray(xy) * [1, -1] - middle) * scale + [1205, 260])

    lines = [project(p) for p in route[::4, :2]]
    duration = rows[-1]["t"]
    trace = []
    out_path = folder / ("report-" + name + ".mp4")
    tmp = out_path.with_suffix(".tmp.mp4")
    with (
        av.open(str(folder / (name + ".mp4"))) as source,
        av.open(str(tmp), "w", options={"movflags": "+faststart"}) as dst,
    ):
        video = dst.add_stream("libx264", rate=5)
        video.width, video.height = 1440, 864
        video.pix_fmt = "yuv420p"
        video.options = {"crf": "19", "preset": "veryfast"}
        audio = dst.add_stream("aac", rate=48000)
        audio.layout = "stereo"
        count = 0
        for i, (frame, row) in enumerate(zip(source.decode(video=0), rows, strict=True)):
            canvas = Image.new("RGB", (1440, 864), BG)
            d = ImageDraw.Draw(canvas)
            label(
                d,
                (28, 13),
                "SPHERE LAB   /   BLACK RUSSIA   /   ПРОВЕРКА УПРАВЛЕНИЯ",
                16,
                BLUE,
                True,
            )
            label(d, (28, 40), "Scooter 5  ·  Вокруг Кремля", 32, FG, True)
            label(d, (1006, 43), f"{row['t']:.1f} / {duration:.1f} с   ·   шаг 0,2 с", 23, DIM)
            image = frame.to_image().resize((960, 540))
            ink = ImageDraw.Draw(image)
            cam = row.get("camera")
            if cam:
                s = cam["station"]
                ahead = route[(route[:, 3] > s + 1.5) & (route[:, 3] < s + 25), :3][::2]
                rot = np.array(cam["rotation"])
                f = 480 / math.tan(math.radians(115.58 / 2))
                v = (ahead - cam["xyz"]) @ rot.T
                coords = []
                for vx, vy, vz in v:
                    if vz > 0.8:
                        px, py = 480 + vx / vz * f, 270 + vy / vz * f
                        if 0 <= px < 960 and 0 <= py < 540:
                            coords.append((px, py))
                            continue
                    if len(coords) > 1:
                        ink.line(coords, fill=BLUE, width=3)
                    coords = []
                if len(coords) > 1:
                    ink.line(coords, fill=BLUE, width=3)
            for u, v in row.get("supports", []):
                x, y = u * 960, v * 540
                ink.ellipse((x - 2, y - 2, x + 2, y + 2), fill=GREEN, outline=BG)
            canvas.paste(image, (28, 99))
            d.rounded_rectangle((1005, 99, 1412, 639), 14, fill=PANEL)
            label(d, (1027, 115), "Маршрут и положение", 23, FG, True)
            d.line(lines, fill=BLUE, width=3)
            trace.append(project(row["xy"]))
            if len(trace) > 1:
                d.line(trace, fill=GREEN, width=4)
            x, y = trace[-1]
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=FG, outline=BG)
            label(d, (1027, 379), "Эталон", 18, BLUE)
            label(d, (1163, 379), "Ход симулятора", 18, GREEN)
            seen = row["position_error"] is not None
            label(
                d,
                (1027, 428),
                "Поза найдена" if seen else "Поиск позиции",
                24,
                GREEN if seen else ORANGE,
                True,
            )
            label(d, (1027, 472), f"Путь   {row['s']:.1f} / {report['route_length']:.1f} ед.", 21)
            label(d, (1027, 508), f"Скорость   {row['actual_velocity']:.1f} ед./с", 21)
            label(d, (1027, 544), f"Руль   {row['steering']:+.2f}", 21)
            pedal = {"coast": "накат", "brake": "тормоз", "throttle": "газ"}[row["pedal"]]
            label(d, (1027, 580), f"Команда   {pedal}", 22, FG, True)
            label(d, (28, 652), "Скорость симулятора · ед./с", 18, GREEN)
            label(d, (729, 652), "От кадра до команды · мс", 18, ORANGE)
            limit = max(200, math.ceil(max(r["frame_to_command_ms"] for r in rows) / 200) * 200)
            plot(d, (28, 691, 650, 81), rows, i, len(rows), "actual_velocity", 10, GREEN)
            plot(d, (729, 691, 680, 81), rows, i, len(rows), "frame_to_command_ms", limit, ORANGE)
            label(d, (31, 774), "0–10 ед./с", 15, DIM)
            label(d, (730, 774), f"0–{limit} мс", 15, DIM)
            label(
                d,
                (28, 817),
                "Браузерный стенд · исходная геометрия и текстуры Ariane · виртуальное время",
                18,
                DIM,
            )
            for packet in video.encode(av.VideoFrame.from_image(canvas)):
                dst.mux(packet)
            sound = av.AudioFrame.from_ndarray(
                np.zeros((2, 9600), np.float32), format="fltp", layout="stereo"
            )
            sound.sample_rate = 48000
            sound.pts = i * 9600
            sound.time_base = Fraction(1, 48000)
            for packet in audio.encode(sound):
                dst.mux(packet)
            count += 1
        if count != report["frame_count"]:
            raise ValueError("mismatched telemetry")
        for stream in (video, audio):
            for packet in stream.encode():
                dst.mux(packet)
    tmp.replace(out_path)
    print(out_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", required=True, type=Path)
    p.add_argument("--run")
    p.add_argument("--circuit", type=Path)
    p.add_argument("--comparisons", default="independent-views.json")
    args = p.parse_args()
    comparisons(args.folder, args.comparisons)
    if args.run:
        if not args.circuit:
            p.error("--circuit required with --run")
        film(args.folder, args.run, args.circuit)
