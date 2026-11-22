"""Visualize saved overlap comparisons; unit is reference-camera step, not metres."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def run(full_path, local_path, output):
    if output.exists():
        raise FileExistsError("output_exists")
    full = json.loads(full_path.read_bytes())
    local = json.loads(local_path.read_bytes())
    if (
        full["baseline_geometry_sha256"] != local["baseline_geometry_sha256"]
        or full["source_manifest_sha256"] != local["source_manifest_sha256"]
        or [r["image"] for r in full["heldout_rows"]] != [r["image"] for r in local["heldout_rows"]]
    ):
        raise ValueError("comparison_inputs_not_paired")
    image = Image.new("RGB", (1850, 1050), "#0b1422")
    d = ImageDraw.Draw(image)
    reg = "C:/Windows/Fonts/segoeui.ttf"
    bold = "C:/Windows/Fonts/segoeuib.ttf"

    def F(size):
        return ImageFont.truetype(reg, size)

    def B(size):
        return ImageFont.truetype(bold, size)

    d.text((65, 42), "fuflo228 · согласование двух вариантов", font=B(40), fill="#f1f6ff")
    d.text(
        (67, 102),
        "Совмещение по 25–28,5 с; сравнение на общих кадрах после 29 с",
        font=F(22),
        fill="#a8bace",
    )
    d.line((65, 153, 1785, 153), fill="#293d53", width=2)

    def graph(box, title, report, color, ceiling, ticks):
        x1, y1, x2, y2 = box
        d.rounded_rectangle(box, radius=18, fill="#142236", outline="#304962", width=2)
        d.text((x1 + 25, y1 + 20), title, font=B(24), fill="#e9f0f9")
        d.text(
            (x1 + 25, y1 + 58),
            f"Медиана {report['heldout']['median']:.2f} · максимум {report['heldout']['maximum']:.2f}",
            font=F(19),
            fill="#9fb8cf",
        )
        left, t, r, b = x1 + 70, y1 + 115, x2 - 35, y2 - 95
        for tick in ticks:
            yy = b - (b - t) * tick / ceiling
            d.line((left, yy, r, yy), fill="#31465b", width=1)
            d.text((x1 + 15, yy - 10), f"{tick:g}", font=F(16), fill="#8ea5bb")
        points = []
        for row in report["heldout_rows"]:
            x = left + (r - left) * (row["seconds"] - 29) / (33.258 - 29)
            y = b - (b - t) * min(row["disagreement_baseline_steps"], ceiling) / ceiling
            points.append((x, y))
        if len(points) > 1:
            d.line(points, fill=color, width=4)
        for x, y in points:
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
        d.text((left, b + 15), "29 с", font=F(16), fill="#9fb3c8")
        d.text((r - 62, b + 15), "33,26 с", font=F(16), fill="#9fb3c8")
        d.text((left, b + 47), "Ед.: медианный шаг базовой камеры", font=F(16), fill="#91a6bc")

    graph(
        (65, 200, 905, 790), "Полный · BA без уточнения фокуса", full, "#ffad72", 18, (0, 5, 10, 15)
    )
    graph(
        (945, 200, 1785, 790),
        "Локальный · BA без уточнения фокуса",
        local,
        "#76dfc3",
        1,
        (0, 0.25, 0.5, 0.75, 1),
    )
    d.rounded_rectangle((65, 830, 1785, 996), radius=16, fill="#142236", outline="#304962", width=2)
    d.text((90, 849), "КАК ЧИТАТЬ", font=B(18), fill="#79dfc5")
    for i, line in enumerate(
        [
            "Оси графиков различаются; показатели — расхождение реконструкций, не ошибка относительно истины.",
            "Ролик и граф совпадений общие; масштаб в метрах и положение скутера относительно камеры неизвестны.",
            "Ни один из вариантов не выбран автоматически для управления: позы в конце всё ещё требуют проверки.",
        ]
    ):
        d.text((90, 882 + i * 28), line, font=F(19), fill="#c1d0df")
    image.save(output, optimize=True)
    print(output.resolve())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("full", type=Path)
    p.add_argument("local", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.full, a.local, a.output)
