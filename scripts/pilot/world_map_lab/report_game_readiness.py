"""Publish the native-game evidence independently of the map simulation results."""

import argparse
import hashlib
import html
import json
from pathlib import Path


def publish(folder, engine_bin, scenario_bin, quarter_dir):
    def read(p):
        return json.loads((folder / p).read_bytes())

    game = read("game-runtime.json")
    boot = read("engine-boot.json")
    quarter = json.loads((quarter_dir / "manifest.json").read_bytes())
    if not boot["moduleRequested"] or not boot["scenarioRequested"]:
        raise ValueError("no browser evidence for the selected engine and scenario")
    files = {}
    for path in (engine_bin, scenario_bin):
        with path.open("rb") as stream:
            if stream.read(4) != b"\0asm":
                raise ValueError("not a WebAssembly module")
            stream.seek(0)
            files[path.name] = dict(
                bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, "sha256").hexdigest()
            )
    for name, module in files.items():
        if boot.get("modules", {}).get(name, {}).get("sha256") != module["sha256"]:
            raise ValueError("build differs from browser module " + name)
    if (
        not any("sphere-journey loaded" in line for line in boot["console"])
        or "static initialisers run" not in boot["engineLog"]
    ):
        raise ValueError("no evidence of scenario and engine initialization")
    missing = [p for p, present in game["mapFiles"].items() if not present]
    probes = (
        read("displacement-probes.json") if (folder / "displacement-probes.json").is_file() else []
    )

    def row(k, v):
        return "<tr><th>" + html.escape(str(k)) + "</th><td>" + html.escape(str(v)) + "</td></tr>"

    goods = "".join(
        row(k, "В архиве" if v else "Отсутствует")
        for k, v in game["map"]["assets"].items()
        if k in ("faggio.dff", "player.dff", "bikev.ifp", "ped.ifp")
    )
    offsets = "".join(
        row(
            f"{r['offset']:+g} ед.",
            (
                "Ошибка %.2f ед." % r["positionError"]
                if r.get("accepted")
                else "Положение не подтверждено"
            )
            if r["ground"]
            else "Нет поверхности в заданной точке",
        )
        for r in probes
    )

    local_probes = [r for r in probes if r.get("ground") and abs(r["offset"]) <= 12]
    recovered = sum(bool(r.get("accepted")) for r in local_probes)

    def fmt(n):
        return f"{n:,}".replace(",", " ")

    doc = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Игровая физика · Black Russia</title>
    <style>*{{box-sizing:border-box}}body{{margin:0;background:#0d191f;color:#e5efed;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1150px;margin:auto;padding:32px 24px}}h1{{font-size:clamp(28px,4vw,45px);line-height:1.15}}h2{{font-size:21px;margin:0 0 12px}}a{{color:#9de6cf}}section{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}article{{background:#15272d;border:1px solid #3d5254;border-radius:12px;padding:20px}}th,td{{padding:6px 0;text-align:left;vertical-align:top;border-bottom:1px solid #35494c}}td{{padding-left:14px}}table{{border-collapse:collapse;width:100%}}code{{color:#eac59a}}.status{{color:#f2c398}}@media(max-width:700px){{section{{grid-template-columns:1fr}}}}</style>
    <main><a href="/">Карта и маршруты</a><h1>Игровая физика GTA San Andreas</h1><p class="status">Игровой проезд пока не подтверждён</p>
    <section><article><h2>Что загрузил браузер</h2><p>Chrome загрузил сборку sa-engine с поддержкой модов и мод сценария Faggio. Движок подтвердил загрузку мода и начал инициализацию. Управляемый персонаж в этом запуске не появился.</p>
    <p>В проверке входных файлов Ariane отсутствуют {" · ".join("<code>" + html.escape(k) + "</code>" for k in missing)}.</p>
    <a href="/journey/engine-boot.json">Журнал загрузки</a> · <a href="/journey/gameplay-proof.json">Версии сборок</a></article>
    <article><h2>Квартал Южного</h2><p>В исходных форматах GTA проверены {fmt(quarter["instances"])} размещений, {quarter["models"]} моделей, {quarter["textures"]} словарей текстур и {quarter["colliders"]} коллизий. Повторное чтение подтвердило координаты, вращения и {quarter["verifiedLODLinks"]} ссылок на модели для дальнего обзора.</p>
    <table>{goods}</table></article>
    <article><h2>Посадка, движение и снос</h2><p>Сценарий ожидает загрузки опорной поверхности. В начале он ставит скутер и персонажа. Во время движения движок обрабатывает управление. Для проверки сноса предусмотрено однократное изменение поперечной скорости. Наблюдатель различает выход у парковки и потерю седла в дороге. Возврат засчитывается после пяти последовательных замеров движения в коридоре маршрута.</p>
    <p>Проверка полос, времени поездки и восстановления после сноса требует полноценного игрового заезда.</p></article>
    <article><h2>Проверка поиска по камере</h2><p>Известное последнее положение и неожиданное смещение виртуальной камеры. На геометрическом стенде два разных кадра подтвердили положение в {recovered} из {len(local_probes)} проверок внутри области поиска. Смещение на 35 единиц проверялось отдельно.</p><table>{offsets}</table>
    <a href="/journey/journey-report.html">Результаты геометрического стенда</a></article></section>
    <p><a href="https://github.com/ghosty2004/sa-engine/blob/d66f65e1937516320d6f3cc6a6cab2a7671e018e/web/README.md">Документация браузерного движка</a> · <a href="https://wiki.multitheftauto.com/wiki/Where_to_buy_GTASA">Совместимые издания классической GTA SA</a></p></main></html>"""
    (folder / "gameplay.html").write_text(doc, encoding="utf8")
    (folder / "gameplay-proof.json").write_text(
        json.dumps(
            dict(
                modules=files,
                recoveryOnGeometricMap=dict(accepted=recovered, tested=len(local_probes)),
                quarter=quarter["hashes"],
                missingFromMap=missing,
                engineDriveVerified=False,
            ),
            indent=2,
        ),
        encoding="utf8",
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("folder", "engine-bin", "scenario-bin", "quarter-dir"):
        cli.add_argument("--" + key, type=Path, required=True)
    args = cli.parse_args()
    publish(args.folder, args.engine_bin, args.scenario_bin, args.quarter_dir)
