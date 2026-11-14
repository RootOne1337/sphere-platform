"""Visual summary of same- and other-recording retrieval, never a pose score."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render(same_path: Path, other_path: Path, output: Path):
    if output.exists():
        raise ValueError("output_exists")
    same, other = (json.loads(p.read_text("utf-8")) for p in (same_path, other_path))
    if (
        same.get("same_recording") is not True
        or same.get("physical_actions") != 0
        or other.get("distinct_recordings") is not True
        or other.get("same_place_ground_truth_known") is not False
        or other.get("physical_actions") != 0
        or same["source_sha256"] != other["source_sha256"]["query"]
    ):
        raise ValueError("incompatible_reports")
    img = Image.new("RGB", (1440, 720), "#091321")
    d = ImageDraw.Draw(img)

    def regular(size):
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", size)

    def bold(size):
        return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", size)

    d.text((68, 42), "SPHERE  /  ПОИСК ПОСЛЕДОВАТЕЛЬНОСТИ", font=bold(18), fill="#54d7c0")
    d.text((68, 82), "Одна запись и другая запись", font=bold(38), fill="#eff5ff")
    d.text(
        (68, 143),
        "Результаты поиска похожего вида, не оценка положения и управления",
        font=regular(20),
        fill="#a8bad1",
    )
    labels = {
        "hypothesis": "Гипотеза",
        "confirming": "Ожидание",
        "ambiguous": "Неоднозначно",
        "unknown": "Не найдено",
    }
    colors = {
        "hypothesis": "#52d7b7",
        "confirming": "#68aaf7",
        "ambiguous": "#f7b85a",
        "unknown": "#73859e",
    }
    rows = [
        (
            "test228 → test228 · разные кадры одного прохода",
            same["multi_candidate"]["states"],
            same["queries"],
        ),
        (
            "fuflo228 → test228 · другая запись",
            other["results"]["diverse"]["states"],
            other["query_frames"],
        ),
    ]
    for row, (title, counts, total) in enumerate(rows):
        if set(counts) - set(labels) or sum(counts.values()) != total or total < 1:
            raise ValueError("invalid_counts")
        y = 200 + row * 185
        d.rounded_rectangle(
            (68, y, 1372, y + 155), radius=16, fill="#101f32", outline="#304762", width=2
        )
        d.text((94, y + 17), title, font=bold(23), fill="#eff5ff")
        d.text((1180, y + 23), f"{total} кадров", font=regular(18), fill="#a8bad1")
        x = 96
        for key in labels:
            width = 1200 * counts.get(key, 0) / total
            if width:
                d.rectangle((x, y + 65, x + width, y + 96), fill=colors[key])
            x += width
        d.text(
            (96, y + 111),
            "   ·   ".join(f"{labels[k]}: {counts.get(k, 0)}" for k in labels),
            font=regular(17),
            fill="#d9e6f5",
        )
    d.text(
        (68, 590),
        "Одинаковое место между разными записями не размечено.",
        font=bold(20),
        fill="#f5d7a1",
    )
    d.text(
        (68, 625),
        "Отказы не измеряют полноту распознавания; гипотезы не подтверждают проезд или координаты.",
        font=regular(19),
        fill="#a8bad1",
    )
    img.save(output)


if __name__ == "__main__":
    base = Path(".local-pilot")
    render(
        base / "test228-merge-attempt-20261027/test228-place-multicandidate-diverse-v1/report.json",
        base / "fuflo228-20261027/visual-place-other-capture-v1/report.json",
        base / "fuflo228-20261027/place-cross-capture-summary-v1.png",
    )
