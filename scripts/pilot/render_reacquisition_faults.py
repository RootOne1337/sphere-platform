"""Create a static timeline from already-saved offline fault experiment."""

import argparse
import json
from pathlib import Path


def render(source: Path, output: Path):
    from PIL import Image, ImageDraw, ImageFont

    report = json.loads(source.read_text(encoding="utf-8"))
    scenarios = report["scenarios"]
    if report["samples"] != 150 or output.exists():
        raise ValueError("unexpected_samples_or_existing_output")
    image = Image.new("RGB", (1500, 420), "#171c28")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = (
        ImageFont.truetype(str(font_path), 20) if font_path.is_file() else ImageFont.load_default()
    )
    small = (
        ImageFont.truetype(str(font_path), 16) if font_path.is_file() else ImageFont.load_default()
    )
    draw.text(
        (28, 18), "fuflo228: local reacquisition under injected faults", font=font, fill="#f1f3f8"
    )
    draw.text(
        (28, 52),
        "Saved same-recording matches; offline simulation; no game control",
        font=small,
        fill="#c4cede",
    )
    colors = {"matched": "#59d39a", "confirming": "#f2b949", "unknown": "#e66671"}
    for y, mode, label in (
        (105, "baseline", "No injected faults"),
        (165, "dropout", "3 short losses"),
        (225, "far_match", "3 false distant matches"),
        (285, "long_dropout", "One longer loss"),
    ):
        rows = scenarios[mode]["rows"]
        if len(rows) != report["samples"]:
            raise ValueError("scenario_rows_mismatch")
        draw.text((28, y), label, font=small, fill="#eef1f5")
        for index, row in enumerate(rows):
            x = 330 + index * 7
            draw.rectangle((x, y - 2, x + 5, y + 18), fill=colors[row["state"]])
            if row["injected"]:
                draw.line((x, y - 6, x + 5, y - 6), fill="#ffffff", width=2)
    draw.text(
        (28, 352),
        "Green: matched hypothesis    Amber: confirming    Red: unknown    White: injected fault",
        font=small,
        fill="#f1f3f8",
    )
    draw.text(
        (28, 383),
        "Not metres, steering, collision avoidance, or proof of arrival.",
        font=small,
        fill="#c4cede",
    )
    image.save(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    render(args.source, args.output)
