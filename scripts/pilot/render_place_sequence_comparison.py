"""Render a bounded, evidence-labelled same-recording comparison."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(ranked_path: Path, diverse_path: Path, output: Path):
    if output.exists():
        raise ValueError("output_exists")
    ranked, diverse = (json.loads(path.read_text("utf-8")) for path in (ranked_path, diverse_path))
    if (
        ranked.get("same_recording") is not True
        or diverse.get("same_recording") is not True
        or ranked.get("physical_actions") != 0
        or diverse.get("physical_actions") != 0
        or ranked.get("source_sha256") != diverse.get("source_sha256")
        or ranked.get("reference_frames") != diverse.get("reference_frames")
        or [r["frame"] for r in ranked["multi_candidate"]["samples"]]
        != [r["frame"] for r in diverse["multi_candidate"]["samples"]]
    ):
        raise ValueError("incompatible_comparison_inputs")
    total = ranked["queries"]
    colors = {
        "hypothesis": "#52d7b7",
        "confirming": "#68aaf7",
        "ambiguous": "#f7b85a",
        "unknown": "#73859e",
    }
    labels = {
        "hypothesis": "Гипотеза",
        "confirming": "Подтверждение",
        "ambiguous": "Неоднозначно",
        "unknown": "Не определено",
    }
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    bold_path = Path("C:/Windows/Fonts/segoeuib.ttf")

    def font(size):
        return ImageFont.truetype(str(font_path), size)

    def bold(size):
        return ImageFont.truetype(str(bold_path), size)

    image = Image.new("RGB", (1440, 810), "#091321")
    draw = ImageDraw.Draw(image)
    draw.text((72, 48), "SPHERE  /  FUFLO228  /  ОФЛАЙН-ЭКСПЕРИМЕНТ", font=bold(19), fill="#54d7c0")
    draw.text((72, 89), "Поиск места по последовательности кадров", font=bold(39), fill="#eff5ff")
    draw.text(
        (72, 150),
        "40 одинаковых кадров запроса · 16 опорных ракурсов · два способа выбора кандидатов",
        font=font(21),
        fill="#a8bad1",
    )
    for number, (name, data) in enumerate(
        (("Обычный рейтинг", ranked), ("Разнесённые кандидаты", diverse))
    ):
        y = 220 + number * 210
        result = data["multi_candidate"]
        states = result["states"]
        if sum(states.values()) != total or set(states) - set(colors):
            raise ValueError("invalid_state_counts")
        draw.rounded_rectangle(
            (72, y, 1368, y + 173), radius=18, fill="#101f32", outline="#304762", width=2
        )
        draw.text((100, y + 22), name, font=bold(27), fill="#eef5ff")
        draw.text(
            (1040, y + 32),
            f"{result['more_than_one_candidate_frames']} кадров с >1 кандидатом",
            font=font(17),
            fill="#a8bad1",
        )
        x = 102
        for kind in ("hypothesis", "confirming", "ambiguous", "unknown"):
            n = states.get(kind, 0)
            width = 1200 * n / total
            if n:
                draw.rectangle((x, y + 82, x + width, y + 115), fill=colors[kind])
            x += width
        text = "   ·   ".join(
            f"{labels[k]}: {states.get(k, 0)}"
            for k in ("hypothesis", "confirming", "ambiguous", "unknown")
        )
        draw.text((102, y + 128), text, font=font(18), fill="#d6e3f2")
    draw.text(
        (72, 665),
        "Гипотеза — похожее место на записи, а не подтверждённая поза или команда движения.",
        font=bold(19),
        fill="#f5d7a1",
    )
    draw.text(
        (72, 706),
        "Опорные и запросные кадры различны, но взяты из одного видео. Независимой поездки нет.",
        font=font(19),
        fill="#a8bad1",
    )
    draw.text(
        (72, 739),
        "Неоднозначный кандидат может быть ошибкой сопоставления или похожим видом — это пока не установлено.",
        font=font(18),
        fill="#a8bad1",
    )
    image.save(output)


if __name__ == "__main__":
    base = Path(".local-pilot/fuflo228-20261027")
    render(
        base / "visual-place-multicandidate-ranked-v2/report.json",
        base / "visual-place-multicandidate-diverse-v2/report.json",
        base / "visual-place-multicandidate-comparison-v2.png",
    )
