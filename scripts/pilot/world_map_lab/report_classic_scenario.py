"""Publish the native route, compiled script and actual engine boot results together."""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

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


def full_world_section(path, route_id):
    if path is None:
        return ""
    world = json.loads(path.read_bytes())
    if world["scope"] != "all-active-source-scenes" or world["routeSha256"] != route_id:
        raise ValueError("full world and spawn scenario differ")
    scenes = world["scenes"]
    size = sum(a["bytes"] for a in world["archives"]) / 1024**3
    peak = max(s["instances"] for s in scenes)
    return f"""<section id="whole-world"><h2>Вся карта Black Russia</h2>
<p>В пакет GTA SA вошли все {len(scenes)} активных сцен Ariane. Расстановки, координаты,
повороты и ссылки на дальние модели сохранены в исходных файлах сцен.</p>
<table><tbody><tr><th>Размещения / определения моделей</th><td>{world["instances"]:,} / {world["modelDefinitions"]:,}</td></tr>
<tr><th>Связи с дальними моделями</th><td>{world["lodLinks"]:,}</td></tr>
<tr><th>Коллизии, привязанные к моделям</th><td>{world["collisions"]:,}</td></tr>
<tr><th>Архивы GTA / объём</th><td>{len(world["archives"])} / {size:.2f} ГиБ</td></tr>
<tr><th>Размещений в крупнейшей сцене</th><td>{peak:,}</td></tr></tbody></table>
<p>В исходнике у {world["unavailableSourceRows"]} размещений отсутствует геометрия.
Физический проезд по полной карте ожидает запуска совместимой игровой базы с расширенными лимитами.</p></section>"""


def controller_section(folder, route_id):
    path = folder / "native-acceptance.json"
    if not path.is_file():
        return ""
    data = json.loads(path.read_bytes())
    if data["routeSha256"] != route_id:
        raise ValueError("controller evidence belongs to a different native route")
    load = data["fullWorld"]
    before = data["original"]
    after = data["preindexedRecovery"]
    walking = data["walking"]
    automatic = data["automaticLens"]
    survey = data["stationaryStart"]
    return f"""<section id="native-tests"><h2>Подготовка физического заезда</h2>
<p>Полная карта прошла испытание с занятыми номерами всех импортируемых моделей.
Проверены {load["scenes"]} сцен, {load["binding"]["remappedInstances"]:,} размещений и {load["binding"]["checkedCollisions"]:,} привязок коллизий.</p>
<table><thead><tr><th>Исходное видео Scooter 4</th><th>Первый тест</th><th>С индексами и восстановлением</th></tr></thead>
<tbody><tr><th>Обработано кадров</th><td>{before["frames"]}</td><td>{after["frames"]}</td></tr>
<tr><th>Кадров с позой</th><td>{before["located"]}</td><td>{after["located"]}</td></tr>
<tr><th>Задержка решения, p95</th><td>{before["p95ms"]:.0f} мс</td><td>{after["p95ms"]:.0f} мс</td></tr></tbody></table>
<p>Сравнение использует один и тот же поток длительностью {data["sourceSeconds"]:.1f} с. Устаревшие кадры пропускаются. Движение на этой записи задавал игрок.</p>
<p>С автоматической калибровкой угол обзора определился на {automatic["calibratedAt"]:.1f} с.
Поза получена на {automatic["located"]} из {automatic["frames"]} обработанных кадров.
Контроллер сформировал {automatic["commandCounts"].get("throttle", 0)} команды газа и {automatic["commandCounts"].get("brake", 0)} команд торможения.
На отдельной проверке неподвижного старта с осмотром по модели карты первая команда шага получена на {survey["t"]:.1f} с.</p>
<p>На исходной геометрии проверены оба пеших участка. Положение восстановлено для {walking["located"]} из {walking["tested"]} отложенных ракурсов.
Игровой скрипт проверяет посадку, {data["gates"]} дорожные точки, остановку и пеший финиш. Живой проезд в классическом клиенте ожидает проверки.</p></section>"""


def cross_world_section(folder, world_manifest, browser_stand=None):
    if folder is None:
        return ""
    if world_manifest is None:
        raise ValueError("cross-world reporting requires the full world manifest")
    paths, _, route_hash = native_route(folder / "sphere-route.json")
    scene = json.loads((folder / "classic-scenario.json").read_bytes())
    index = json.loads((folder / "world-rgbd/index.json").read_bytes())
    probe = json.loads((folder / "heldout-rgbd.json").read_bytes())
    if {scene["routeSha256"], index["routeSha256"], probe["routeSha256"]} != {route_hash} or (
        scene["worldManifestSha256"] != hashlib.sha256(world_manifest.read_bytes()).hexdigest()
        or probe["indexSha256"]
        != hashlib.sha256((folder / "world-rgbd/index.json").read_bytes()).hexdigest()
    ):
        raise ValueError("cross-world evidence does not match this journey")
    checks = []
    for i, (title, path) in enumerate(
        zip(("Подойти к Faggio", "Доехать и остановиться", "Выйти и дойти"), paths, strict=True)
    ):
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        results = [r for r in probe["rows"] if r["phase"] == i]
        checks.append(
            f"<tr><th>{title}</th><td>{length:,.1f}</td><td>{sum(r['found'] for r in results)} / {len(results)}</td></tr>"
        )
    browser_link = ""
    if browser_stand:
        address = urlsplit(browser_stand)
        if address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("the browser stand must be on loopback")
        browser_link = f'<p><a href="{html.escape(browser_stand, quote=True)}">Открыть браузерный стенд полного маршрута</a></p>'
    return f"""<section id="cross-map"><h2>Через всю карту на Faggio</h2>{browser_link}
<p>Проверка по отдельным изображениям геометрии карты с приблизительно известным положением.</p>
<table><thead><tr><th>Участок</th><th>Длина, ед.</th><th>Найдена поза</th></tr></thead><tbody>{"".join(checks)}</tbody></table>
<p>Проверок с кадром из другого места: {len(probe["negatives"])}. Принято ложных положений: {sum(v["accepted"] for v in probe["negatives"])}.</p>
<p>В миссии камера закреплена на персонаже. Проверяются посадка, {scene["orderedNativeRoadChecks"]} дорожных точек, остановка и пеший финиш.</p>
<p><strong>Заезд в клиенте GTA SA ожидает проверки. Запись игрового окна появится после физического прогона.</strong></p></section>"""


def publish(folder, world_manifest=None, cross_course=None, browser_stand=None):
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
<main><a href="/">← Карта Black Russia</a><h1>{"Маршруты Black Russia" if cross_course else title} в GTA San Andreas</h1>
{cross_world_section(cross_course, world_manifest, browser_stand)}
{f"<h2>{title} · контрольный квартал</h2>" if cross_course else ""}
<p>Пешком к скутеру → круг на Faggio → пешком до цели.</p>
<section><h2>Запуск игры</h2><p><strong>Проезд в оригинальной GTA SA ожидает проверки.</strong></p>
<p>Для Windows собран игровой сценарий с персонажем, припаркованным Faggio 462 и камерой от первого лица. Посадку, ускорение, поворот и выход обрабатывает игра.</p>
<p>Браузерный порт выполнил {len(boot["completedBootSteps"])} шагов контрольной загрузки. {boot_info} Последний запрос движка<br><code>{latest}</code></p></section>
{controller_section(folder, route_id)}
{full_world_section(world_manifest, route_id)}
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
    cli.add_argument("--world-manifest", type=Path)
    cli.add_argument("--cross-course", type=Path, help="compiled and tested long itinerary")
    cli.add_argument("--browser-stand", help="local browser engine page for the full route")
    args = cli.parse_args()
    publish(args.folder, args.world_manifest, args.cross_course, args.browser_stand)
