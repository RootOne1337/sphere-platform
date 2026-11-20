"""Publish a local navigation report bound to an installed map revision and specific run outputs."""

import argparse
import hashlib
import html
import json
import re
from pathlib import Path


def publish(args):
    root = args.folder
    scene = json.loads((root.parent / "detail-scene.json").read_bytes())
    game = json.loads((root / "complete-game-replay.json").read_bytes())
    checks = json.loads((root / "combined-views.json").read_bytes())
    table = []
    movies = []
    titles = {}
    for name in args.run:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            raise ValueError("invalid run name")
        run = json.loads((root / (name + ".json")).read_bytes())
        if run.get("placementRevision") != scene["revision"]:
            raise ValueError("different map revision")
        film = root / ("report-" + name + ".mp4")
        if film.is_file():
            movies.append(film)
        finish = run["outcome"] == "vehicle_camera_trace_end_confirmed"
        condition = {
            "nominal": "Штатный старт",
            "shifted": "Старт со смещением",
            "dim": "Смещение и затемнение",
        }[run["scenario"]]
        if name.startswith("checked-"):
            variant = "сверка рендера при остановке"
        elif name.startswith("wide-"):
            variant = "расширенный набор ракурсов"
        else:
            variant = "базовый набор ракурсов"
        titles[film.name] = f"{condition} · {variant}"
        table.append(
            f"<tr><td>{condition}<small>{html.escape(name)}</small></td><td>{'Финиш' if finish else 'Остановка'}</td><td>{run['distance_units']:.1f}</td><td>{run['endpoint_error']:.2f}</td><td>{run['frame_to_command_p95_ms']:.0f}</td><td>{run['accepted_error_over_one']}</td></tr>"
        )
    if not movies:
        raise ValueError("render at least one synchronized movie")
    options = "".join(
        f'<option value="{m.name}">{html.escape(titles[m.name])}</option>' for m in movies
    )
    selector = (
        f'<label>Выбрать видео <select id="pick">{options}</select></label>'
        if len(movies) > 1
        else ""
    )
    summary = f"""<p>Архив Scooter 4 без HUD · {game["duration"]:.1f} с. Из {game["sampled"]} проверенных кадров геометрия дала согласованный вариант на {game["located"]}. В коридоре шириной ±2,2 ед. оказались {game["within_corridor"]} из них. Самый длинный интервал между найденными положениями с учётом краёв записи — {game["longest_fix_interval_s"]:.1f} с.</p><p>На фиксированной выборке из 11 кадров {sum(r["rank"] == 1 for r in checks)} поз заняли первое место при сравнении с шестью смещёнными вариантами. Точные игровые координаты камеры в архиве неизвестны.</p>"""
    coverage = (
        '<img src="game-coverage.png" alt="Карта позиций и интервал без наблюдений">'
        if (root / "game-coverage.png").is_file()
        else ""
    )
    output = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Scooter 5 · От первого лица</title>
<style>html{{color-scheme:dark;background:#0a1420;color:#edf5f6;font:17px/1.5 system-ui,sans-serif}}body{{max-width:1320px;margin:0 auto;padding:25px 3vw 60px}}header{{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap}}nav{{display:flex;gap:20px}}a,b{{color:#76e3ce}}h1{{font-size:clamp(28px,4vw,48px);line-height:1.12}}h2{{margin-top:42px}}video,img{{width:100%;height:auto;border-radius:8px}}video{{aspect-ratio:5/3;background:#112333}}p{{max-width:88ch}}small{{display:block;color:#a1b8ca}}section{{overflow:auto}}table{{border-collapse:collapse;width:100%}}td,th{{padding:.65em;text-align:left;border-bottom:1px solid #2c4150}}th,label{{color:#a1b8ca}}select{{padding:6px;margin:8px}}header a{{white-space:nowrap}}</style>
<header><b>SPHERE LAB / BLACK RUSSIA</b><nav><a href="/">Планировщик</a><a href="/review">19 мест на карте</a><a href="/detail?view=first&amp;x=-2887.75&amp;y=2448.75&amp;z=8.41982&amp;yaw=180&amp;pitch=2&amp;hfov=115.58&amp;radius=160">Открыть старт в 3D</a></nav></header><h1>Scooter 5 · Вокруг Кремля</h1><p>Проезд по исходной карте в браузерном симуляторе. Контроллер получает положение и темп по изображению. Белый маркер на схеме показывает фактическое положение скутера в симуляторе.</p>{selector}<video id="movie" controls playsinline preload="metadata" src="{movies[0].name}"></video>
<h2>Заезды</h2><section><table><thead><tr><th>Условия</th><th>Итог</th><th>По пути, ед.</th><th>До финиша, ед.</th><th>Кадр → команда, p95 мс</th><th>Поз с ошибкой &gt;1 ед.</th></tr></thead><tbody>{"".join(table)}</tbody></table></section><p>Шаг симуляции 0,2 с. Время вычислений измерено по часам ПК. Затемнение меняет яркость и гамму кадра. Проверка зазора охватывает статическую поверхность карты.</p><h2>Сверка с записью игры</h2>{summary}{coverage}<img src="game-map-comparison.png" alt="Пара кадров из игры слева и соответствующий вид исходной карты справа"><script>document.querySelector("#pick")?.addEventListener("change",e=>document.querySelector("#movie").src=e.target.value)</script></html>"""
    page = root / "report.html"
    page.write_text(output, encoding="utf-8")
    files = {}
    illustrations = [root / "game-map-comparison.png"]
    if coverage:
        illustrations.append(root / "game-coverage.png")
    for path in [page, *illustrations, *movies]:
        with path.open("rb") as stream:
            files[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    tmp = root / "published.partial.json"
    tmp.write_text(json.dumps(dict(revision=scene["revision"], files=files)), encoding="utf-8")
    tmp.replace(root / "published.json")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", required=True, type=Path)
    p.add_argument("--run", nargs="+", required=True)
    publish(p.parse_args())
