"""Render read-only evidence boards from two saved sparse reconstructions.

PCA is fitted independently to each camera trace. Quantile-clipped scatter is
reported, never used as a map, and no reconstructed quantity is called metres.
The source video/geometry is read only; this does not rerun reconstruction.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / ".local-pilot/fuflo228-20261027"
OUT = ROOT / "docs/audits/2026-10-27/fuflo228-evidence-boards-v1"
FONT = "C:/Windows/Fonts/segoeui.ttf"
BOLD = "C:/Windows/Fonts/segoeuib.ttf"


def font(size, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def evidence(relative, selected):
    path = BASE / relative / "geometry.json"
    raw = path.read_bytes()
    data = json.loads(raw)
    points = np.asarray(data["points"], dtype=np.float64)
    cameras = data["cameras"]
    centers = np.asarray([row["center"] for row in cameras], dtype=np.float64)
    ticks = np.asarray([row["ticks_90k"] / 90000 for row in cameras], dtype=np.float64)
    if (
        points.ndim != 2
        or points.shape[1] < 3
        or len(points) > 100000
        or centers.ndim != 2
        or centers.shape[1] != 3
        or not 2 <= len(centers) <= 256
        or not np.isfinite(points[:, :3]).all()
        or not np.isfinite(centers).all()
        or not np.isfinite(ticks).all()
        or np.any(np.diff(ticks) <= 0)
    ):
        raise ValueError("invalid_evidence_geometry")
    origin = centers.mean(axis=0)
    _, _, vh = np.linalg.svd(centers - origin, full_matrices=False)
    # PCA basis signs are arbitrary: pin sign for reproducible display only.
    basis = vh[:2].copy()
    for axis in basis:
        if axis[np.argmax(np.abs(axis))] < 0:
            axis *= -1
    xy = (points[:, :3] - origin) @ basis.T
    trace = (centers - origin) @ basis.T
    # Preserve the entire camera trace while clipping extreme point-cloud tails.
    lo = np.minimum(np.percentile(xy, 1, axis=0), trace.min(axis=0))
    hi = np.maximum(np.percentile(xy, 99, axis=0), trace.max(axis=0))
    visible = ((xy >= lo) & (xy <= hi)).all(axis=1)
    return dict(
        name=relative,
        selected=selected,
        points=xy[visible],
        points_total=len(xy),
        points_shown=int(visible.sum()),
        trace=trace,
        ticks=ticks,
        minimum=lo,
        maximum=hi,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def rgb_at(t):
    stops = [(0.0, (102, 151, 255)), (0.5, (57, 221, 200)), (1.0, (246, 218, 98))]
    for (a, x), (b, y) in zip(stops, stops[1:]):
        if t <= b:
            k = max(0, min(1, (t - a) / (b - a)))
            return tuple(int(xi * (1 - k) + yi * k) for xi, yi in zip(x, y))
    return stops[-1][1]


def header(image, eyebrow, title, subtitle):
    draw = ImageDraw.Draw(image)
    draw.text((90, 50), eyebrow, font=font(20, True), fill="#73ddc7")
    draw.text((88, 91), title, font=font(46, True), fill="#f3f7fd")
    draw.text((92, 160), subtitle, font=font(24), fill="#a8bace")
    draw.line((90, 210, image.width - 90, 210), fill="#263b50", width=2)
    return draw


def card(draw, box, caption, value, extra):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=18, fill="#132236", outline="#304761", width=2)
    draw.text((x1 + 25, y1 + 17), caption.upper(), font=font(16, True), fill="#83a6c2")
    draw.text((x1 + 25, y1 + 45), value, font=font(32, True), fill="#f5f8fd")
    draw.text((x1 + 25, y1 + 91), extra, font=font(17), fill="#a8bed1")


def plot(draw, bounds, data, *, warning=False):
    x1, y1, x2, y2 = bounds
    draw.rounded_rectangle(bounds, radius=18, fill="#0d1827", outline="#2a4058", width=2)
    inner = (x1 + 62, y1 + 35, x2 - 32, y2 - 63)
    left, top, right, bottom = inner
    lo, hi = data["minimum"].copy(), data["maximum"].copy()
    span = np.maximum(hi - lo, 1e-8)
    # Keep 1:1 PCA units in both axes; center in the available plot rectangle.
    scale = min((right - left) / span[0], (bottom - top) / span[1]) * 0.94
    midpoint = (lo + hi) / 2
    center = ((left + right) / 2, (top + bottom) / 2)

    def project(v):
        return (
            center[0] + (float(v[0]) - midpoint[0]) * scale,
            center[1] - (float(v[1]) - midpoint[1]) * scale,
        )

    for value in np.arange(np.ceil(lo[0] / 2) * 2, hi[0] + 1e-8, 2):
        a, b = project((value, lo[1])), project((value, hi[1]))
        draw.line((a, b), fill="#22364a", width=1)
        draw.text((a[0] - 12, bottom + 8), f"{value:g}", font=font(15), fill="#8095aa")
    for value in np.arange(np.ceil(lo[1] / 2) * 2, hi[1] + 1e-8, 2):
        a, b = project((lo[0], value)), project((hi[0], value))
        draw.line((a, b), fill="#22364a", width=1)
        draw.text((left - 45, a[1] - 9), f"{value:g}", font=font(15), fill="#8095aa")
    for p in data["points"]:
        x, y = project(p)
        if left <= x <= right and top <= y <= bottom:
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill="#8e805f")
    ticks, trace = data["ticks"], data["trace"]
    for i in range(1, len(trace)):
        # Never imply a continuous reconstructed path through a missing >1 s gap.
        if ticks[i] - ticks[i - 1] > 1:
            continue
        a, b = project(trace[i - 1]), project(trace[i])
        color = rgb_at(float(ticks[i] / 33.258))
        draw.line((a, b), fill=color, width=4)
    for i, p in enumerate(trace):
        x, y = project(p)
        color = rgb_at(float(ticks[i] / 33.258))
        r = 5 if warning and ticks[i] >= 29 else 4
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
        if warning and ticks[i] >= 29:
            draw.ellipse((x - r - 2, y - r - 2, x + r + 2, y + r + 2), outline="#ffb769", width=2)
    sx, sy = project(trace[0])
    ex, ey = project(trace[-1])
    draw.ellipse((sx - 11, sy - 11, sx + 11, sy + 11), outline="#ffffff", width=4)
    draw.line((ex - 9, ey - 9, ex + 9, ey + 9), fill="#ffba83", width=4)
    draw.line((ex - 9, ey + 9, ex + 9, ey - 9), fill="#ffba83", width=4)
    draw.text((left, bottom + 37), "PCA · условные единицы", font=font(16), fill="#8aa0b6")


def footer(draw, y, lines):
    for i, line in enumerate(lines):
        draw.text((90, y + i * 27), line, font=font(18), fill="#9fb1c4")


def comparison(old, new):
    im = Image.new("RGB", (2300, 1460), "#0a1321")
    d = header(
        im,
        "SPHERE  /  FUFLO228  /  ГЕОМЕТРИЯ",
        "Два восстановления одного прохода",
        "Опорные точки и положение камеры · разреженная реконструкция, не дорожная карта",
    )
    card(
        d,
        (90, 245, 600, 370),
        "Предыдущее",
        f"{len(old['trace'])} / {old['selected']}",
        f"камер · {old['points_total']:,} точек".replace(",", " "),
    )
    card(
        d,
        (620, 245, 1130, 370),
        "Новое",
        f"{len(new['trace'])} / {new['selected']}",
        f"камер · {new['points_total']:,} точек".replace(",", " "),
    )
    card(d, (1150, 245, 1660, 370), "Длина записи", "33,258 с", "915 кадров · исходное видео")
    card(d, (1680, 245, 2210, 370), "Масштаб", "условный", "независимая PCA в каждом графике")
    d.text((95, 412), "01  ПРЕДЫДУЩЕЕ", font=font(20, True), fill="#c0cfdf")
    d.text((1200, 412), "02  НОВОЕ", font=font(20, True), fill="#c0cfdf")
    plot(d, (90, 455, 1130, 1230), old)
    plot(d, (1170, 455, 2210, 1230), new, warning=True)
    footer(
        d,
        1280,
        [
            "●  Цветные точки — положения камеры во времени; ○ начало, × последнее положение.",
            "●  Золотистые точки — восстановленные признаки. Оранжевая обводка справа: участок 29–33 с требует проверки.",
            "●  Пропуск старой реконструкции не соединён линией. Каждая PCA независима; оси не метры и графики не совмещены.",
            f"●  Для читаемости показано {old['points_shown']:,} / {old['points_total']:,} и {new['points_shown']:,} / {new['points_total']:,} точек (обрезаны крайние координаты).".replace(
                ",", " "
            ),
        ],
    )
    return im


def detail(new):
    im = Image.new("RGB", (2100, 1560), "#0a1321")
    d = header(
        im,
        "SPHERE  /  FUFLO228  /  ДЕТАЛЬ",
        "Восстановленные ориентиры",
        "Новая геометрия · отдельный увеличенный вид · PCA по траектории камеры",
    )
    plot(d, (90, 250, 1600, 1360), new, warning=True)
    card(d, (1650, 250, 2010, 380), "Камеры", "123 / 123", "отобранных ракурса")
    card(d, (1650, 400, 2010, 530), "3D-признаки", "22 014", "не классифицированы")
    card(d, (1650, 550, 2010, 680), "Проекция", "0,969 px", "внутренняя ошибка SfM")
    card(d, (1650, 700, 2010, 830), "Масштаб", "неизвестен", "связь с дорогой не доказана")
    d.text((1665, 895), "КАК ЧИТАТЬ", font=font(19, True), fill="#78ddc9")
    for i, line in enumerate(
        [
            "○  начало",
            "×  последний ракурс",
            "Цвет: начало → конец",
            "Оранжевый контур:",
            "29–33 с требуют проверки",
        ]
    ):
        d.text((1665, 935 + i * 34), line, font=font(20), fill="#b8c9dc")
    footer(
        d,
        1412,
        [
            f"Показано {new['points_shown']:,} из {new['points_total']:,} точек; крайние координаты обрезаны для читаемости.".replace(
                ",", " "
            ),
            "Проекция PCA не является картой дороги или подтверждением фактической траектории скутера.",
        ],
    )
    return im


def coverage(old, new):
    im = Image.new("RGB", (2100, 1100), "#0a1321")
    d = header(
        im,
        "SPHERE  /  FUFLO228  /  ПОКРЫТИЕ",
        "Где восстановились ракурсы",
        "Каждая отметка — одна восстановленная камера; это не оценка качества дороги между отметками",
    )
    x1, x2 = 330, 1960
    duration = 33.258
    for y, label, data in ((370, "ПРЕДЫДУЩЕЕ", old), (590, "НОВОЕ", new)):
        d.rounded_rectangle(
            (90, y - 70, 2010, y + 90), radius=16, fill="#132236", outline="#304761", width=2
        )
        d.text((115, y - 38), label, font=font(21, True), fill="#d8e5f1")
        d.text((115, y), f"{len(data['trace'])} камер", font=font(19), fill="#98adc3")
        d.line((x1, y, x2, y), fill="#4a6076", width=3)
        for t in data["ticks"]:
            x = x1 + (x2 - x1) * t / duration
            c = rgb_at(float(t / duration))
            d.line((x, y - 23, x, y + 23), fill=c, width=4)
        if label == "ПРЕДЫДУЩЕЕ":
            a = x1 + (x2 - x1) * 10.807 / duration
            b = x1 + (x2 - x1) * 12.341 / duration
            d.line((a, y + 36, b, y + 36), fill="#ffad77", width=5)
            d.text((a, y + 46), "пропуск", font=font(16), fill="#ffbd90")
            d.text(
                (x1 + (x2 - x1) * 28.258 / duration - 5, y - 57),
                "28,26 с",
                font=font(16),
                fill="#ffbd90",
            )
        else:
            a = x1 + (x2 - x1) * 29 / duration
            d.line((a, y + 36, x2, y + 36), fill="#ffad77", width=5)
            d.text((a - 24, y + 46), "29–33 с: проверить позы", font=font(16), fill="#ffbd90")
    for sec in range(0, 31, 5):
        x = x1 + (x2 - x1) * sec / duration
        d.text((x - 8, 725), f"{sec}", font=font(18), fill="#a8bace")
    d.text((x2 - 90, 725), "33,258 с", font=font(18), fill="#a8bace")
    d.rounded_rectangle((90, 800, 2010, 995), radius=18, fill="#111e2d", outline="#2d465d", width=2)
    d.text((120, 825), "ЧТО ВИДНО ИЗ ДАННЫХ", font=font(19, True), fill="#74ddc5")
    footer(
        d,
        865,
        [
            "Старая: внутри пропуск примерно 10,81–12,34 с; после 28,26 с восстановленных камер нет.",
            "Новая: камеры связаны до конца видео, но на 29–33 с есть признаки неустойчивой геометрии.",
            "Покрытие ракурсами не подтверждает поверхность дороги, метры, столкновения или качество автономного движения.",
        ],
    )
    return im


def main():
    if OUT.exists():
        raise FileExistsError("evidence_board_output_already_exists")
    old = evidence("sparse-job-v2", 66)
    new = evidence("sparse-denseviews-simple-focal-v2", 123)
    OUT.mkdir(parents=True)
    comparison(old, new).save(OUT / "01-comparison.png", optimize=True)
    detail(new).save(OUT / "02-detail.png", optimize=True)
    coverage(old, new).save(OUT / "03-coverage.png", optimize=True)
    provenance = {
        key: {
            "geometry_sha256": data["sha256"],
            "cameras": len(data["trace"]),
            "points_total": data["points_total"],
            "points_shown": data["points_shown"],
            "projection": "PCA camera centers independently; scatter clipped 1st-99th percentiles per axis; full camera trace kept",
            "metric_scale_known": False,
            "road_verified": False,
        }
        for key, data in (("old", old), ("new", new))
    }
    (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
