"""Render comparable offline localization experiments, without claiming navigation readiness."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(paths: list[Path], output: Path) -> None:
    if output.exists() or len(paths) != 4:
        raise ValueError("output_exists_or_incomplete")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    baseline = records[0]
    indices = [sample["source_index"] for sample in baseline["samples"]]
    names = (
        "3 участка · дескрипторы",
        "3 участка · с отслеживанием",
        "8 участков · дескрипторы",
        "8 участков · с отслеживанием",
    )
    colors = {"localized": "#55ddbd", "confirming": "#6daaf8", "unknown": "#72849c"}
    for data in records:
        if (
            data.get("same_capture") is not False
            or data.get("physical_actions") != 0
            or data.get("execution_qualified") is not False
            or data.get("offline_media_clock") is not True
            or data.get("route_id") != baseline.get("route_id")
            or data.get("capture_manifest_sha256") != baseline.get("capture_manifest_sha256")
            or [sample["source_index"] for sample in data["samples"]] != indices
            or set(data["counts"]) - set(colors)
            or sum(data["counts"].values()) != len(indices)
        ):
            raise ValueError("incompatible_evidence")
    img = Image.new("RGB", (1600, 1050), "#091321")
    draw = ImageDraw.Draw(img)

    def font(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", n)

    def bold(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", n)

    draw.text((72, 40), "SPHERE  /  НАВИГАЦИЯ  /  ОФЛАЙН-ПРОВЕРКА", font=bold(19), fill="#58dfc8")
    draw.text((72, 78), "Ориентиры на повторной записи", font=bold(39), fill="#f2f7ff")
    draw.text(
        (72, 137),
        "Карта test228 → другой проход test1488 · 46 кадров, 6–16 секунд",
        font=font(21),
        fill="#a8bad1",
    )
    for index, (name, data) in enumerate(zip(names, records)):
        y = 196 + 165 * index
        draw.rounded_rectangle(
            (72, y, 1528, y + 144), radius=16, fill="#102035", outline="#304965", width=2
        )
        draw.text((98, y + 14), name, font=bold(23), fill="#edf5ff")
        timings = data["compute_ms"]
        draw.text(
            (1090, y + 17),
            f"p50 {timings['p50']:.0f} мс  ·  p95 {timings['p95']:.0f} мс",
            font=font(18),
            fill="#b8cce2",
        )
        x = 100
        for key in ("localized", "confirming", "unknown"):
            width = 1120 * data["counts"].get(key, 0) / len(indices)
            if width:
                draw.rectangle((x, y + 58, x + width, y + 89), fill=colors[key])
            x += width
        late = sum(
            s["compute_ms"] > 250 and s["pose"]["state"] == "localized" for s in data["samples"]
        )
        draw.text(
            (98, y + 102),
            f"Поза: {data['counts'].get('localized', 0)}   ·   подтверждение: {data['counts'].get('confirming', 0)}   ·   неизвестно: {data['counts'].get('unknown', 0)}",
            font=font(18),
            fill="#d9e6f5",
        )
        if late:
            draw.text((1100, y + 100), f"{late} поза > 250 мс", font=bold(18), fill="#ffc17b")
    draw.text(
        (72, 891),
        "Поза прошла внутренние проверки — это ещё не подтверждение положения или безопасной дороги.",
        font=bold(20),
        fill="#ffd89c",
    )
    draw.text(
        (72, 928),
        "Часы видео смоделированы; показано только время расчёта. Поток и управление не измерялись.",
        font=font(19),
        fill="#afc2d9",
    )
    draw.text(
        (72, 966),
        "Другая запись · без команд устройству · метрическая точность неизвестна",
        font=font(18),
        fill="#8195ad",
    )
    img.save(output)


if __name__ == "__main__":
    base = Path(".local-pilot/test228-merge-attempt-20261027")
    names = ("descriptor-v1", "anchored_flow-v1", "descriptor-top8-v1", "anchored_flow-top8-v1")
    render(
        [base / f"cross-session-sparse-{name}/report.json" for name in names],
        base / "cross-session-sparse-comparison-top8-v1.png",
    )
