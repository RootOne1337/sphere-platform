"""Publish the native route, compiled script and actual engine boot results together."""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path

from scripts.pilot.world_map_lab.native_route import native_route


def vehicle_probe_section(folder):
    path = folder / "vehicle-physics-audit/result.json"
    if not path.is_file():
        return ""
    probe = json.loads(path.read_bytes())
    rows = []
    for name, trial in probe["models"].items():
        wheels = int(trial["power"]["controllerWheels"])
        distance = float(trial["inputEffectXY"])
        rows.append(
            f"<tr><th>{html.escape(name)}</th><td>{wheels}</td><td>{distance:.2f}</td></tr>"
        )
    seconds = float(probe["parameters"]["commandSeconds"])
    rev = html.escape(probe["openSARevision"][:8])
    return f"""<section><h2>Отклик моделей на газ в OpenSA</h2>
<p>Версия {rev}. Два запуска каждой модели на плоской поверхности с одинаковыми начальными условиями.
Через {seconds:g} с измерено расстояние по горизонтали между положениями с газом и без газа.</p>
<table><thead><tr><th>Модель из IMG</th><th>Колёса в физике</th><th>Разница, ед.</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<p>Массу и масштаб колёс задали одинаковыми для сравнения. Замер проверяет работу загрузчика и контроллера OpenSA.</p></section>"""


def publish(folder):
    def read(name):
        return json.loads((folder / name).read_bytes())

    plan, _, route_id = native_route(folder / "classic-map/sphere-route.json")
    map_proof = read("map/manifest.json")
    classic = read("classic-pc/classic-scenario.json")
    staged = read("classic-map/sphere-scenario.json")
    floor = read("classic-surface.json")
    boot = read("boot/engine-boot.json")
    runtime = read("game-runtime.json")
    hashes = {p["routeSha256"] for p in (map_proof, classic, staged, floor)}
    if hashes != {route_id} or floor["collisionSha256"] != staged["streamedCollisionSha256"]:
        raise ValueError("different map, route or collision records")
    for name in ("main.scm", "script.img"):
        if (
            hashlib.sha256((folder / "classic-map/data/script" / name).read_bytes()).hexdigest()
            != classic["files"][name]
        ):
            raise ValueError("changed compiled scenario")
    module = folder / "build/mods/sphere-journey/sphere_journey.wasm"
    if (
        boot["modules"]["sphere_journey.wasm"]["sha256"]
        != hashlib.sha256(module.read_bytes()).hexdigest()
    ):
        raise ValueError("browser and staged observer differ")
    rows = []
    for label, path, leg in zip(
        ("Подход к Faggio", "Проезд вокруг квартала", "Пешком до цели"),
        plan,
        floor["legs"],
        strict=True,
    ):
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        dz = "—" if leg["maxHeightError"] is None else f"{leg['maxHeightError']:.3f}"
        rows.append(
            f"<tr><th>{label}</th><td>{length:.2f}</td><td>{leg['supported']} / {leg['samples']}</td><td>{dz}</td></tr>"
        )
    missing = ", ".join(html.escape(k) for k, v in runtime["mapFiles"].items() if not v)
    boot_info = (
        "Движок вывел кадр мира."
        if boot["worldRendered"]
        else "До первого кадра мира загрузка не дошла."
    )
    latest = html.escape(boot["fileOpens"][-1] if boot["fileOpens"] else "—")
    title = html.escape(
        json.loads((folder / "classic-map/sphere-route.json").read_bytes()).get("name", "Маршрут")
    )
    markup = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · GTA San Andreas</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#0c131a;color:#e9f1f2;font:17px/1.6 "Segoe UI",sans-serif}}main{{max-width:910px;margin:42px auto;padding:0 26px 56px}}a{{color:#75dfce}}h1{{font-size:clamp(32px,5vw,54px);line-height:1.08;margin:34px 0 12px}}h2{{font-size:23px;margin:28px 0 8px}}p{{margin:8px 0;color:#cbd7df}}strong{{color:#ffe1a3}}section{{background:#17212b;padding:6px 20px 20px;border-radius:12px;margin-top:22px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #34414e;padding:9px 5px;text-align:right;font-variant-numeric:tabular-nums}}th:first-child{{text-align:left}}code{{overflow-wrap:anywhere;font-size:14px}}@media(max-width:580px){{main{{padding:0 12px}}section{{padding:4px 10px 14px}}table{{font-size:13px}}}}</style>
<main><a href="/">← Карта Black Russia</a><h1>{title} в GTA San Andreas</h1>
<p>Пешком к скутеру → круг на Faggio → пешком до цели.</p>
<section><h2>Запуск игры</h2><p><strong>Проезд в оригинальной GTA SA ожидает проверки.</strong></p>
<p>Для Windows собран игровой сценарий с персонажем, припаркованным Faggio 462 и камерой от первого лица. Посадку, ускорение, поворот и выход обрабатывает игра.</p>
<p>Браузерный порт выполнил {len(boot["completedBootSteps"])} шагов контрольной загрузки. {boot_info} Последний запрос движка<br><code>{latest}</code></p></section>
{vehicle_probe_section(folder)}
<h2>Опора под маршрутом</h2><p>Высоты измерены по треугольникам коллизий упакованной карты. Длины и высоты приведены в единицах игрового мира.</p>
<table><thead><tr><th>Участок</th><th>Длина</th><th>Точки с опорой</th><th>Макс. разница высот</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p>{map_proof["instances"]} размещений · {map_proof["models"]} моделей · {map_proof["colliders"]} моделей коллизий.</p>
<h2>Какие файлы нужны для запуска</h2><p>Подготовщик создаёт отдельную игровую папку из совместимой классической GTA San Andreas. Сейчас в комплекте Ariane отсутствуют</p>
<code>{missing}</code><p><a href="https://store.rockstargames.com/game/buy-grand-theft-auto-the-trilogy">Классическая трилогия у Rockstar</a></p></main></html>"""
    dest = folder.parent / "native-stand.html"
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(markup, encoding="utf8")
    tmp.replace(dest)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--folder", type=Path, required=True)
    publish(cli.parse_args().folder)
