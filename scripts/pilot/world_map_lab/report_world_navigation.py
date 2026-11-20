"""Publish the local navigation report and matched before/after district views."""

import argparse
import html
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def read(path):
    return json.loads(path.read_bytes())


def compare(folder, previous, font_dir):
    base = Image.new("RGB", (1836, 1200), "#101c25")
    draw = ImageDraw.Draw(base)

    def font(size, bold=False):
        return ImageFont.truetype(str(font_dir / ("segoeuib.ttf" if bold else "segoeui.ttf")), size)

    draw.text(
        (36, 20), "Black Russia   /   Улицы и пешеходные пути", fill="#f2f5ee", font=font(38, True)
    )
    draw.text(
        (38, 80),
        "Те же координаты и масштаб до и после пересборки дорожного слоя.",
        fill="#bacdd2",
        font=font(23),
    )
    sections = [("batyrevo", "Батырево", (1778, 2110)), ("uzhny", "Южный", (2275, -1997))]
    for k, (slug, name, center) in enumerate(sections):
        y = 144 + k * 485
        current = folder / "atlas" / slug
        meta = read(current / "ariane-world-render.json")
        b = meta["bounds"]
        width, height = meta["views"]["top"]["dimensions"]
        scale = width / (b["right"] - b["left"])
        x0 = round((center[0] - b["left"]) * scale) - 520
        y0 = round((b["top"] - center[1]) * scale) - 240
        draw.text(
            (40, y), f"{name}    X {center[0]}   Y {center[1]}", fill="#a8e7d1", font=font(24, True)
        )
        for j, (root, tag) in enumerate(((previous / slug, "До"), (current, "После"))):
            left = 40 + j * 890
            image = Image.open(root / "ariane-world-map-with-roads.png").convert("RGB")
            if image.size != (width, height):
                raise ValueError("district extents do not match")
            crop = image.crop((x0, y0, x0 + 1040, y0 + 480)).resize(
                (860, 397), Image.Resampling.LANCZOS
            )
            base.paste(crop, (left, y + 49))
            draw.rounded_rectangle(
                (left + 10, y + 59, left + 105, y + 99), radius=7, fill="#15212a"
            )
            draw.text((left + 22, y + 63), tag, fill="white", font=font(20, True))
    draw.text(
        (40, 1132),
        "Бирюзовый — дорожные материалы     •     Янтарный — дополнительные покрытия     •     Розовый — пешеходные покрытия",
        fill="#b8cbd0",
        font=font(21),
    )
    base.save(folder / "street-comparison.jpg", quality=96)


def publish(folder, previous, font_dir):
    compare(folder, previous, font_dir)
    audit = read(folder / "world-navigation-audit.json")
    retest = read(folder / "fixed-pair-recheck.json")
    geometry = read(folder / "geometry.json")
    visible = read(folder / "atlas/visible-streets.json")[0]
    manifests = [audit[k]["manifest"] for k in ("drive", "walk")]
    if (
        any(m["geometrySha256"] != geometry["geometrySha256"] for m in manifests)
        or visible["geometrySha256"] != geometry["geometrySha256"]
    ):
        raise ValueError("audit inputs have mixed revisions")

    def num(value):
        return f"{int(round(value)):,}".replace(",", " ")

    def cell(v):
        return f"<td>{html.escape(str(v))}</td>"

    def row(*vals):
        return "<tr>" + "".join(map(cell, vals)) + "</tr>"

    metrics = []
    for mode, title in (("drive", "Транспорт"), ("walk", "Пешком")):
        r = audit[mode]
        pairs = retest[mode]["pairs"]
        metrics.append(
            row(
                title,
                num(r["manifest"]["polygons"]),
                f"{100 * r['largestComponentFraction']:.1f}%",
                f"{sum(p['before'] == 'complete' for p in pairs)} / {len(pairs)}",
                f"{sum(p['after'] == 'complete' for p in pairs)} / {len(pairs)}",
                f"{r['coveredSamples']} / {r['sourceSamples']}",
            )
        )
    sections = "".join(
        row(
            k,
            v["start"][:2],
            v["end"][:2],
            "Путь построен" if v["status"] == "complete" else "Точка вне покрытия",
            num(v["length"]),
        )
        for k, v in retest["sections"].items()
    )
    trips = Counter(t["status"] for t in retest["trips"])
    drive, walk = manifests
    examples = [num(e["length"]) for e in audit["drive"]["routeExamples"]]
    page = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Black Russia · Проверка дорожной сети</title>
<style>
:root{{font:16px/1.55 'Segoe UI',system-ui,sans-serif;color:#eaf3ed;background:#101b21}}*{{box-sizing:border-box}}main{{max-width:1180px;margin:auto;padding:30px 22px 70px}}h1{{font-size:clamp(32px,5vw,55px);line-height:1.05;letter-spacing:-.04em}}h2{{font-size:26px;margin:42px 0 12px}}p{{max-width:95ch}}img{{display:block;width:100%;height:auto;border:1px solid #384a52;border-radius:12px}}a{{color:#a9ead4}}small{{color:#bfd0d2}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;border-bottom:1px solid #384a52;padding:10px 12px}}th{{color:#a9ead4}}.hero{{font-size:19px}}li{{margin:9px 0}}</style>
<main><small>SPHERE LAB · BLACK RUSSIA · ПРОВЕРКА ИСХОДНОЙ КАРТЫ</small><h1>От дорожного покрытия<br>к пути между точками</h1>
<p class="hero">Для всей внешней карты собраны автомобильная и пешеходная навигационные сетки. Планировщик ищет переходы между уровнями и соседними тайлами. В смешанном режиме он проверяет обе части пути до общей точки выхода.</p>
<p><a href="http://127.0.0.1:8817/">Открыть планировщик A → B</a> · <a href="atlas/ariane-world-map.html">Атлас с детализацией районов</a> · <a href="atlas/ariane-world-3d.html">Цветная модель</a></p>
<h2>Что изменилось на тех же стартах и целях</h2><div class="table"><table><tr><th>Режим</th><th>Полигоны</th><th>В крупнейшей связной части¹</th><th>До</th><th>После</th><th>Проверка исходных покрытий²</th></tr>{"".join(metrics)}</table></div>
<p>¹ Доля площади построенной сетки в горизонтальной проекции. Этажи учитываются отдельно. ² Из исходных дорожных или пешеходных треугольников выбрано по 1 000 точек пропорционально площади. Проверялась доступность в тех же X и Y с допуском по высоте 0,65. В выборку входят кромки и участки под препятствиями. Полнота распознавания всех улиц требует независимой разметки.</p>
<p>Контрольные пары выбраны на предыдущей сетке с весом по площади. Обе координаты каждой пары сохранены. Это тест поиска по статической геометрии. Отдельная проверка сочетания способов движения дала {trips["complete"]} из {len(retest["trips"])} достижимых целей. Для этих проверок использовались автомобильные старты и отдельно выбранные пешеходные цели.</p>
<h2>Откуда брались разрывы</h2><ul>
<li>Первичный фильтр пропускал материалы перекрёстков, переходов и грунтовых улиц. В исходных моделях проверены 4 488 текстур пологих поверхностей. Проверенные примеры включают отдельные рисунки разметки и асфальта в Арзамасе, Батырево и Южном.</li>
<li>На северо-западном подъёме асфальт и коллизия посередине лежат на высоте 39,98. Фильтр сравнивал высоты по обе стороны от ячейки с пределом на один шаг. После исправления сетка допускает непрерывный склон и сохраняет предел отдельной ступени 0,25 для транспорта.</li>
<li>В файле воды есть разнесённые по высоте поверхности. При построении переходов они проверяются на высоте физического слоя. Для общей карты улиц выбран диапазон высот, содержащий дорожную геометрию. На цветном виде сверху подземные и закрытые крышей покрытия скрываются по глубине. Контроль глубины общего вида выполняется с шагом {visible["depthPixelStride"]} пикс.</li>
<li>Для длинных маршрутов исчерпывался внутренний пул поисковых узлов. Теперь поиск продолжает обход по порталам той же сетки. Два сквозных автомобильных теста дали {examples[0]} и {examples[1]} игровых единиц.</li></ul>
<a href="street-comparison.jpg"><img alt="Два участка в одинаковом масштабе до и после исправления" src="street-comparison.jpg"></a>
<h2>Контрольные участки</h2><div class="table"><table><tr><th>Участок</th><th>A · XY</th><th>B · XY</th><th>Результат</th><th>Длина, ед.</th></tr>{sections}</table></div>
<h2>Что проверяет карта</h2><p>В обработку вошли {num(geometry["placements"])} размещений наружной сцены. Найдено {num(geometry["placedTriangles"]["0"])} исходных треугольников коллизий. Коробки и сферы дополнительно учтены как препятствия, для сфер взята охватывающая коробка. Для {geometry["unresolvedCollisionPlacements"]} размещений коллайдер по имени модели отсутствует.</p>
<p>Шаг в горизонтальной плоскости {drive["cell"]} ед., по высоте {drive["heightStep"]} ед. Радиусы транспортного и пешеходного профилей {drive["radius"]} и {walk["radius"]} ед. Переход между тайлами строится через порталы на совместимой высоте. При нескольких уровнях под одним кликом пользователь выбирает высоту. Смешанный режим рассматривает несколько точек перехода и сравнивает длины с весом движения на транспорте 1/3. Это параметр планирования. Физическая скорость в игре отдельно не измерялась.</p>
<h2>Что ещё ограничивает проезд</h2><p>Часть улиц и отдельных площадок остаётся отсоединённой. На некоторых границах участки разделяет газон, каменистая поверхность или ограждение. Там требуется проверка фактического въезда. Смешанный материал с травой и асфальтом может занимать один треугольник, поэтому точная граница колеи требует анализа его текстурных координат. Наличие покрытия и построение пути не устанавливают направление полос, радиус поворота конкретной машины или право на парковку.</p>
<p>Для следующей приёмки нужны независимо размеченные улицы и переходы в слабых районах. Для живой поездки нужны подтверждённые положение и направление по кадру, контроль полосы и отдельный тест замыкания маршрута в игре. Эталонные пары, отказы и координаты сохранены для повторения. Эмулятор при этой проверке не использовался.</p>
<p><a href="world-navigation-audit.json">Замеры и координаты</a> · <a href="fixed-pair-recheck.json">Повтор на тех же точках</a> · <a href="world-gap-review.json">Разрывы и материалы в исходных моделях</a> · <a href="https://recastnav.com/group__recast.html">Метод построения навигационной сетки Recast</a></p>
</main></html>"""
    (folder / "navigation-report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--previous-atlas", type=Path, required=True)
    p.add_argument("--font-dir", type=Path, required=True)
    args = p.parse_args()
    publish(args.folder, args.previous_atlas, args.font_dir)
