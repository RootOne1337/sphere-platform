"""Publish the native-game evidence independently of the map simulation results."""

import argparse
import base64
import hashlib
import html
import json
from pathlib import Path

import numpy as np


def driving_observation(run, chart=None):
    data = json.loads((run / "rgb-drive.json").read_bytes())
    route = json.loads((run / "route.json").read_bytes())
    rows = data["rows"]
    out = dict(
        run=run.name,
        result=data["result"],
        frames=len(rows),
        seconds=rows[-1]["simTime"],
        commandP95Ms=round(float(np.percentile([r["commandMs"] for r in rows], 95)), 1),
        finishError=round(
            float(np.linalg.norm(np.subtract(rows[-1]["actual"], route["legs"][-1]["path"][-1]))), 3
        ),
        routeHash=hashlib.sha256((run / "route.json").read_bytes()).hexdigest(),
    )
    offset = data.get("disturbance")
    if offset:
        step = next(
            i
            for i, r in enumerate(rows)
            if r["frame"] == offset["frame"] and r["disturbance"] == offset
        )
        leg = rows[step]["phase"]
        path = np.asarray(route["legs"][leg]["path"])[:, :2]
        segments = np.diff(path, axis=0)
        norm = np.maximum((segments * segments).sum(axis=1), 1e-9)
        distances = []
        for r in rows[step:]:
            if r["phase"] != leg:
                break
            delta = np.array(r["actual"][:2]) - path[:-1]
            t = np.clip((delta * segments).sum(axis=1) / norm, 0, 1)
            distances.append(float(np.linalg.norm(delta - segments * t[:, None], axis=1).min()))
        good = [d < 1.0 and rows[step + i]["groundSpeed"] > 0.3 for i, d in enumerate(distances)]
        returned = next((i for i in range(len(good) - 4) if all(good[i : i + 5])), None)
        out.update(
            offset=offset["offset"],
            initialError=round(distances[0], 3),
            rejoinSeconds=round(rows[step + returned]["simTime"] - rows[step]["simTime"], 2)
            if returned is not None
            else None,
            confirmSeconds=round(rows[step + returned + 4]["simTime"] - rows[step]["simTime"], 2)
            if returned is not None
            else None,
        )
        if chart is not None:
            from matplotlib.figure import Figure

            figure = Figure(figsize=(6.2, 3.2), layout="constrained", facecolor="#15272d")
            ax = figure.subplots()
            ax.set_facecolor("#15272d")
            times = [
                r["simTime"] - rows[step]["simTime"] for r in rows[step : step + len(distances)]
            ]
            ax.axhspan(0, 1, color="#284c46")
            ax.axhline(1, color="#8ed5ad", ls="--", lw=1)
            ax.plot(times, distances, color="#95dcef", lw=2.1)
            if returned is not None:
                ax.scatter(times[returned], distances[returned], s=35, color="#f6c993", zorder=4)
            ax.set_ylim(bottom=0)
            ax.set_xlim(left=0)
            ax.spines[:].set_visible(False)
            ax.tick_params(colors="#c3d7d9")
            ax.set_ylabel("Расстояние до пути, ед.", color="#dceae9")
            ax.set_xlabel("После сноса, с модельного времени", color="#dceae9")
            ax.grid(axis="y", lw=0.5, color="#426269", alpha=0.65)
            figure.savefig(chart, dpi=150)
    return out


def publish(folder, engine_bin, scenario_bin, quarter_dir, displaced_run, control_run):
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

    holdout = read("displacement-holdout.json")
    extra = [r for r in holdout if r["ground"] and abs(r["offset"]) <= 12]
    negatives = [r for r in probes + holdout if r["ground"] and abs(r["offset"]) > 20]
    boot_b = read("native-boot-gxt/engine-boot.json")
    trace = read("native-trace/engine-boot.json")
    if (
        not boot_b["testLanguage"]
        or boot_b["modules"]["sa_game_bg.wasm"]["sha256"] != files[engine_bin.name]["sha256"]
        or any(
            r["modules"]["sphere_journey.wasm"]["sha256"] != files[scenario_bin.name]["sha256"]
            for r in (boot_b, trace)
        )
    ):
        raise ValueError("boot probes require matching scenario and unmodified A/B engine")
    last_open = trace["fileOpens"][-1] if trace["fileOpens"] else "Нет записи"
    boot_summary = dict(
        baselineSteps=len(boot["completedBootSteps"]),
        languageSteps=len(boot_b["completedBootSteps"]),
        lastTracedOpen=last_open,
        worldRendered=boot_b["worldRendered"],
    )
    chart = folder / "recovery-distance.png"
    motion = driving_observation(displaced_run, chart)
    chart_url = "data:image/png;base64," + base64.b64encode(chart.read_bytes()).decode("ascii")
    baseline = driving_observation(control_run)
    if (
        baseline["routeHash"] != motion["routeHash"]
        or "offset" in baseline
        or "offset" not in motion
    ):
        raise ValueError("different control route or missing disturbance")
    offset_tests = dict(
        accepted=sum(bool(r.get("accepted")) for r in extra),
        tested=len(extra),
        unavailable=sum(not r["ground"] for r in holdout),
        rejected=sum(not r["accepted"] for r in negatives),
        outside=len(negatives),
    )
    recovery_text = (
        "Возврат не подтверждён"
        if motion["rejoinSeconds"] is None
        else f"Первый из пяти замеров в пределах одной единицы от пути получен через {motion['rejoinSeconds']} с. Пятым замером возврат подтверждён через {motion['confirmSeconds']} с."
    )

    def fmt(n):
        return f"{n:,}".replace(",", " ")

    doc = f"""<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Игровая физика · Black Russia</title>
    <style>*{{box-sizing:border-box}}body{{margin:0;background:#0d191f;color:#e5efed;font:16px/1.55 system-ui,sans-serif}}main{{max-width:1150px;margin:auto;padding:32px 24px}}h1{{font-size:clamp(28px,4vw,45px);line-height:1.15}}h2{{font-size:21px;margin:0 0 12px}}a{{color:#9de6cf}}section{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}article{{min-width:0;overflow-wrap:anywhere;background:#15272d;border:1px solid #3d5254;border-radius:12px;padding:20px}}th,td{{padding:6px 0;text-align:left;vertical-align:top;border-bottom:1px solid #35494c}}td{{padding-left:14px}}table{{border-collapse:collapse;width:100%}}code{{color:#eac59a}}.status{{color:#f2c398}}@media(max-width:700px){{section{{grid-template-columns:1fr}}}}</style>
    <main><a href="/">Карта и маршруты</a><h1>Игровая физика GTA San Andreas</h1><p class="status">Игровой проезд пока не подтверждён</p>
    <section><article><h2>Что загрузил браузер</h2><p>Chrome загрузил сборку sa-engine с поддержкой модов и мод сценария Faggio. Движок подтвердил загрузку мода и начал инициализацию. Управляемый персонаж в этом запуске не появился.</p>
    <p>С исходным комплектом движок завершил {boot_summary["baselineSteps"]} шага запуска. С тестовым словарём GXT завершено {boot_summary["languageSteps"]} шагов, включая настройку окна и ввода. Последнее открытие файла в диагностической сборке — <code>{html.escape(last_open)}</code>.</p><p>В проверке входных файлов Ariane отсутствуют {" · ".join("<code>" + html.escape(k) + "</code>" for k in missing)}.</p>
    <a href="/journey/engine-boot.json">Журнал загрузки</a> · <a href="/journey/native-boot-gxt/engine-boot.json">Запуск со словарём</a> · <a href="/journey/native-trace/engine-boot.json">Запросы файлов</a> · <a href="/journey/gameplay-proof.json">Измерения и версии</a></article>
    <article><h2>Квартал Южного</h2><p>В исходных форматах GTA проверены {fmt(quarter["instances"])} размещений, {quarter["models"]} моделей, {quarter["textures"]} словарей текстур и {quarter["colliders"]} коллизий. Повторное чтение подтвердило координаты, вращения и {quarter["verifiedLODLinks"]} ссылок на модели для дальнего обзора.</p>
    <table>{goods}</table></article>
    <article><h2>Посадка, движение и снос</h2><p>Сценарий ожидает загрузки опорной поверхности. В начале он ставит скутер и персонажа. Во время движения движок обрабатывает управление. Для проверки сноса предусмотрено однократное изменение поперечной скорости. Наблюдатель различает выход у парковки и потерю седла в дороге. Возврат засчитывается после пяти последовательных замеров движения в коридоре маршрута.</p>
    <h2>Снос на геометрическом стенде</h2><p>Поперечный сдвиг {motion["offset"]} ед. при движении. {recovery_text} Пеший финиш: {motion["result"]}, {motion["seconds"]} с модельного времени. Контроль без сноса: {baseline["result"]}, {baseline["seconds"]} с.</p><img style="width:100%;height:auto" src="{chart_url}" alt="Расстояние до маршрута по кадрам. Зелёная полоса соответствует отклонению до одной единицы."></article>
    <article><h2>Проверка поиска по камере</h2><p>Известное последнее положение и неожиданное смещение виртуальной камеры. На геометрическом стенде два разных кадра подтвердили положение в {recovered} из {len(local_probes)} проверок внутри области поиска. На дополнительных точках подтверждено {offset_tests["accepted"]} из {offset_tests["tested"]} доступных позиций. Без опорной поверхности: {offset_tests["unavailable"]}. Дальние контрольные смещения отклонены в {offset_tests["rejected"]} из {offset_tests["outside"]} случаев.</p><table>{offsets}</table>
    <a href="/journey/displacement-probes.json">Поиск по ракурсам</a> · <a href="/journey/displacement-holdout.json">Дополнительные точки</a></article></section>
    <p><a href="https://github.com/ghosty2004/sa-engine/blob/d66f65e1937516320d6f3cc6a6cab2a7671e018e/web/README.md">Документация браузерного движка</a> · <a href="https://wiki.multitheftauto.com/wiki/Where_to_buy_GTASA">Совместимые издания классической GTA SA</a></p></main></html>"""
    (folder / "gameplay.html").write_text(doc, encoding="utf8")
    (folder / "gameplay-proof.json").write_text(
        json.dumps(
            dict(
                modules=files,
                recoveryOnGeometricMap=dict(accepted=recovered, tested=len(local_probes)),
                bootComparison=boot_summary,
                holdout=offset_tests,
                displacedRun=motion,
                controlRun=baseline,
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
    for key in (
        "folder",
        "engine-bin",
        "scenario-bin",
        "quarter-dir",
        "displaced-run",
        "control-run",
    ):
        cli.add_argument("--" + key, type=Path, required=True)
    args = cli.parse_args()
    publish(
        args.folder,
        args.engine_bin,
        args.scenario_bin,
        args.quarter_dir,
        args.displaced_run,
        args.control_run,
    )
