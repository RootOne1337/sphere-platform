"""Draw the archived RGB position proposals and the longest interval without a fix."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

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


def render(folder, circuit):
    route = np.array(json.loads(circuit.read_bytes())["trace"])
    data = json.loads((folder / "complete-game-replay.json").read_bytes())
    candidates = [r for r in data["rows"] if r["station"] is not None]
    if len(candidates) < 2:
        raise ValueError("need at least two proposals")
    left, right = max(
        zip(candidates, candidates[1:]),
        key=lambda pair: pair[1]["capture_s"] - pair[0]["capture_s"],
    )
    image = Image.new("RGB", (1400, 760), BG)
    draw = ImageDraw.Draw(image)
    label(draw, (35, 22), "SPHERE LAB   /   BLACK RUSSIA   /   АРХИВ SCOOTER 4", 17, BLUE, True)
    label(draw, (35, 58), "Где камера находится по записи без HUD", 35, FG, True)
    draw.rounded_rectangle((35, 130, 720, 723), 16, fill=PANEL)
    label(draw, (58, 147), "Расчётные позиции на исходной карте", 23, FG, True)
    xy = np.vstack([route[:, :2], [r["xyz"][:2] for r in candidates]]) * [1, -1]
    mid = (xy.max(axis=0) + xy.min(axis=0)) / 2
    scale = min(560 / np.ptp(xy[:, 0]), 435 / np.ptp(xy[:, 1]))

    def point(xy):
        return tuple((np.array(xy) * [1, -1] - mid) * scale + [380, 412])

    draw.line([point(p) for p in route[::2, :2]], fill=BLUE, width=4)
    span = route[
        (route[:, 3] >= min(left["station"], right["station"]))
        & (route[:, 3] <= max(left["station"], right["station"]))
    ]
    for i in range(0, len(span) - 7, 13):
        draw.line([point(p) for p in span[i : i + 7, :2]], fill=ORANGE, width=6)
    for r in candidates:
        x, y = point(r["xyz"][:2])
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=GREEN)
    label(draw, (53, 658), "● Положение по кадру", 17, GREEN)
    draw.line([(259, 671), (278, 671)], fill=BLUE, width=3)
    label(draw, (284, 658), "Маршрут", 17, BLUE)
    draw.line([(389, 671), (398, 671)], fill=ORANGE, width=3)
    draw.line([(402, 671), (411, 671)], fill=ORANGE, width=3)
    label(draw, (418, 658), "Интервал без позы", 17, ORANGE)
    label(draw, (775, 153), "Кадры с геометрическим совпадением", 22, DIM)
    label(draw, (772, 187), f"{data['located']} из {data['sampled']}", 52, FG, True)
    label(draw, (775, 277), f"Из них в коридоре ±2,2 ед. — {data['within_corridor']}", 22, DIM)
    label(draw, (775, 353), "Самый длинный перерыв", 22, ORANGE, True)
    label(draw, (775, 393), f"{left['capture_s']:.2f}–{right['capture_s']:.2f} с", 32, FG, True)
    label(draw, (775, 451), f"Последняя позиция — {left['station']:.1f} ед. по маршруту.", 20)
    label(draw, (775, 487), f"Следующая — {right['station']:.1f} ед.", 20)
    for r in data["rows"]:
        x = 780 + int(550 * r["capture_s"] / data["duration"])
        draw.line(
            [(x, 583), (x, 610)], fill=GREEN if r["station"] is not None else "#566476", width=3
        )
    label(draw, (775, 617), "0 c", 17, DIM)
    label(draw, (1260, 617), f"{data['duration']:.1f} c", 17, DIM)
    label(draw, (775, 672), "Одна выборка на 200 мс · время из записи", 18, DIM)
    image.save(folder / "game-coverage.png", optimize=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--circuit", type=Path, required=True)
    args = p.parse_args()
    render(args.folder, args.circuit)
