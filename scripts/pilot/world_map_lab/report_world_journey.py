"""Publish measured RGB attempts alongside the planned cross-world itinerary."""

import argparse
import html
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
from PIL import Image, ImageDraw


def read(path):
    return json.loads(path.read_bytes())


def inspect(directory):
    data = read(directory / "rgb-drive.json")
    trace = data["rows"]
    route = read(directory / "route.json")
    offsets = [math.dist(r["actual"], r["estimated"]) for r in trace]
    return (
        dict(
            id=directory.name,
            outcome=data["result"],
            frames=len(trace),
            seconds=trace[-1]["simTime"],
            planned=sum(leg["length"] for leg in route["legs"]),
            progress=trace[-1]["distance"],
            finishError=math.dist(trace[-1]["actual"], route["legs"][-1]["path"][-1]),
            poseP95=float(np.percentile(offsets, 95)),
            poseMax=max(offsets),
            commandP50=float(np.percentile([r["commandMs"] for r in trace], 50)),
            commandP95=float(np.percentile([r["commandMs"] for r in trace], 95)),
            confirmed=sum(r["visualConfirmed"] for r in trace),
            modes=[mode["mode"] for mode in route["legs"]],
            phases=sorted({r["phase"] for r in trace}),
        ),
        trace,
        route,
    )


def build(folder, city, cross):
    short, _, _ = inspect(city)
    long, rows, route = inspect(cross)
    surface = read(folder / "surface-audit.json")
    config = read(folder / "route.json")
    if route["legs"] != config["legs"]:
        raise ValueError("cross-world trace belongs to a different itinerary")
    bounds = config["terrain"]["bounds"]
    with Image.open(folder / "terrain.jpg") as src:
        atlas = src.convert("RGB")

    def coord(p):
        return (
            (p[0] - bounds["left"]) / (bounds["right"] - bounds["left"]) * atlas.width,
            (bounds["top"] - p[1]) / (bounds["top"] - bounds["bottom"]) * atlas.height,
        )

    draw = ImageDraw.Draw(atlas)
    for leg in route["legs"]:
        line = [coord(p) for p in leg["path"]]
        draw.line(line, fill="#0c2434", width=10, joint="curve")
        draw.line(line, fill="#65cbff", width=6, joint="curve")
    draw.line([coord(r["actual"]) for r in rows], fill="#f8d073", width=3, joint="curve")
    for p, color in [
        (route["legs"][0]["path"][0], "#fff"),
        (route["legs"][-1]["path"][-1], "#60e5c6"),
        (rows[-1]["actual"], "#ffd05d"),
    ]:
        x, y = coord(p)
        draw.ellipse((x - 7, y - 7, x + 7, y + 7), fill=color, outline="#122a31", width=2)
    atlas.save(folder / "journey-overview.jpg", quality=94)

    def description(run):
        labels = {
            "arrived": "Финиш подтверждён",
            "surface_blocked": "Поверхность ограничила движение",
            "localization_lost": "Потеря положения",
            "finish_mismatch": "Расхождение на финише",
            "time_limit": "Вышло время",
            "transfer_out_of_reach": "Расхождение у пересадки",
        }
        result = html.escape(labels.get(run["outcome"], run["outcome"]))
        return f"""<h3>{result}</h3><p>{run["progress"]:,.1f} / {run["planned"]:,.1f} ед. по маршруту · {run["seconds"]:.1f} с</p>
        <dl><dt>Положение подтверждено по кадру</dt><dd>{run["confirmed"]} / {run["frames"]}</dd>
        <dt>До цели в конце попытки</dt><dd>{run["finishError"]:.2f} ед.</dd>
        <dt>Ошибка оценки позиции, P95</dt><dd>{run["poseP95"]:.2f} ед.</dd>
        <dt>От начала получения кадра до команды, P50 / P95</dt><dd>{run["commandP50"]:.0f} / {run["commandP95"]:.0f} мс</dd></dl>
        <a href="/api/journey/trace?id={run["id"]}">Покадровый журнал</a>"""

    query = urlsplit(read(folder / "city-trip.json")["url"]).query
    actual_link = (
        ' · <a href="/journey/cross-camera.mp4">Видео фактической попытки</a>'
        if (cross / "film.json").is_file()
        else ""
    )
    doc = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Проверка поездки по изображению</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#0c171d;color:#e7f0f1;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1300px;margin:auto;padding:24px clamp(16px,4vw,48px) 48px}}header,nav,.legend{{display:flex;gap:20px;align-items:center;flex-wrap:wrap}}header{{justify-content:space-between}}h1{{font-size:clamp(26px,4vw,46px);line-height:1.12;margin:20px 0}}h2{{font-size:21px;margin:0}}h3{{font-size:18px;color:#8be4ce;margin:5px 0}}a{{color:#91dfd2}}section{{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(300px,1fr);gap:20px}}article,figure{{margin:0;background:#13242b;border:1px solid #33474d;border-radius:12px;padding:18px}}article+article{{margin-top:14px}}figure img{{width:100%;height:auto;display:block}}dt{{color:#c4d1d5}}dd{{margin:0 0 8px;font-weight:600}}p{{margin:8px 0 14px}}.legend{{font-size:14px}}small{{color:#c4d1d5}}@media(max-width:760px){{section{{grid-template-columns:1fr}}}}</style><main>
    <header><h1>Проверка локализации на карте</h1><nav><a href="/explore">Открыть мир</a><a href="/review">19 участков карты</a></nav></header>
    <p>Камера от первого лица, исходная геометрия и известный старт. Кинематический стенд ведёт независимый учёт положения. Проверка физики GTA, анимаций и правил полос в игровом заезде ещё впереди.</p>
    <section><figure><img src="/journey/journey-overview.jpg" alt="Южный на юго-востоке, Нижний на северо-западе, расчётный и фактический пути"><figcaption class="legend"><span style="color:#65cbff">━ Рассчитанный путь</span><span style="color:#f8d073">━ Движение под управлением камеры</span></figcaption></figure>
    <div><article><h2>Через всю карту · Faggio</h2>{description(long)} · <a href="/journey/film.mp4">Видео рассчитанного пути</a>{actual_link}</article>
    <article><h2>Пешком → скутер → пешком в Южном</h2>{description(short)} · <a href="/journey/city-camera.mp4">Видео попытки</a> · <a href="/explore?{html.escape(query)}">Повторить</a></article></div></section>
    <p><small>Положение измерено в единицах исходной карты. Проверка геометрии охватила {sum(x["samples"] for x in surface["legs"])} точек вдоль длинного маршрута. Время вычислений измерено на этой машине.</small></p></main></html>"""
    (folder / "journey-report.html").write_text(doc, encoding="utf8")
    (folder / "journey-report.json").write_text(
        json.dumps(dict(city=short, cross=long), indent=2), encoding="utf8"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("folder", "city", "cross"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    build(args.folder, args.city, args.cross)
