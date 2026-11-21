"""Visualize measured offline localizer states on a distinct capture."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(first: Path, second: Path, output: Path):
    if output.exists():
        raise ValueError("output_exists")
    a, b = (json.loads(p.read_text("utf-8")) for p in (first, second))
    if (
        a.get("same_capture") is not False
        or b.get("same_capture") is not False
        or a.get("physical_actions") != 0
        or b.get("physical_actions") != 0
        or a.get("execution_qualified") is not False
        or b.get("execution_qualified") is not False
        or a.get("route_id") != b.get("route_id")
        or a.get("capture_manifest_sha256") != b.get("capture_manifest_sha256")
        or [r["source_index"] for r in a["samples"]] != [r["source_index"] for r in b["samples"]]
    ):
        raise ValueError("incompatible_evidence")
    img = Image.new("RGB", (1440, 730), "#091321")
    d = ImageDraw.Draw(img)

    def font(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", n)

    def bold(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", n)

    d.text((68, 42), "SPHERE  /  ПОВТОРНЫЙ ПРОХОД  /  ОФЛАЙН", font=bold(18), fill="#54d7c0")
    d.text((68, 82), "Проверка карты на другой записи", font=bold(38), fill="#eff5ff")
    d.text(
        (68, 142),
        "Карта test228 → свежие кадры test1488 · 6–16 секунд",
        font=font(20),
        fill="#a8bad1",
    )
    labels = {
        "localized": "Поза прошла проверки",
        "confirming": "Подтверждение",
        "unknown": "Не определено",
    }
    colors = {"localized": "#52d7b7", "confirming": "#68aaf7", "unknown": "#73859e"}
    for index, (title, data) in enumerate(
        (("Дескрипторы и PnP", a), ("Дескрипторы, PnP и оптический поток", b))
    ):
        y = 200 + index * 185
        counts = data["counts"]
        total = len(data["samples"])
        if sum(counts.values()) != total or set(counts) - set(labels) or not total:
            raise ValueError("invalid_counts")
        d.rounded_rectangle(
            (68, y, 1372, y + 155), radius=16, fill="#101f32", outline="#304762", width=2
        )
        d.text((96, y + 17), title, font=bold(24), fill="#eff5ff")
        d.text((1170, y + 23), f"{total} кадров", font=font(18), fill="#a8bad1")
        x = 96
        for name in labels:
            width = 1200 * counts.get(name, 0) / total
            if width:
                d.rectangle((x, y + 65, x + width, y + 97), fill=colors[name])
            x += width
        d.text(
            (96, y + 112),
            "   ·   ".join(f"{labels[k]}: {counts.get(k, 0)}" for k in labels),
            font=font(18),
            fill="#d9e6f5",
        )
    d.text(
        (68, 586),
        "Проверенная алгоритмом поза не означает проверенную дорогу или ошибку в метрах.",
        font=bold(20),
        fill="#f5d7a1",
    )
    d.text(
        (68, 625),
        "Проходы различны; точное положение, свободный путь и управление ещё не размечены.",
        font=font(19),
        fill="#a8bad1",
    )
    img.save(output)


if __name__ == "__main__":
    base = Path(".local-pilot/test228-merge-attempt-20261027")
    render(
        base / "cross-session-sparse-descriptor-v1/report.json",
        base / "cross-session-sparse-anchored_flow-v1/report.json",
        base / "cross-session-sparse-summary-v1.png",
    )
