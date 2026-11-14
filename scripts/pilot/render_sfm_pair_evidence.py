"""Display saved real frame pairs and already-computed diagnostic counts."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def run(report_path, images, output):
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if (
        data.get("scope") != "pairwise_not_reconstruction"
        or len(data.get("pairs", [])) != 6
        or output.exists()
    ):
        raise ValueError("invalid_pair_evidence_or_existing_output")
    image = Image.new("RGB", (1520, 1540), "#0b1422")
    draw = ImageDraw.Draw(image)
    reg = "C:/Windows/Fonts/segoeui.ttf"
    bold = "C:/Windows/Fonts/segoeuib.ttf"
    draw.text(
        (45, 28),
        "fuflo228 · кадры в проблемных участках",
        font=ImageFont.truetype(bold, 34),
        fill="#eef4fc",
    )
    draw.text(
        (46, 77),
        "Реальные кадры записи · сравнение признаков, не восстановленная траектория",
        font=ImageFont.truetype(reg, 19),
        fill="#a1b4c9",
    )
    for row_number, pair_index in enumerate((0, 2, 4)):
        pair = data["pairs"][pair_index]
        y = 125 + row_number * 450
        for j, frame in enumerate(pair["frames"]):
            with Image.open(images / f"{frame:08d}.png") as src:
                thumb = src.convert("RGB").resize((640, 360), Image.Resampling.LANCZOS)
            x = 45 + j * 695
            image.paste(thumb, (x, y))
            draw.rounded_rectangle((x + 10, y + 10, x + 190, y + 46), radius=8, fill="#0c1828")
            draw.text(
                (x + 20, y + 14),
                f"{pair['seconds'][j]:.3f} с",
                font=ImageFont.truetype(bold, 19),
                fill="#f3f8ff",
            )
        orb, sift = pair["methods"]
        info = (
            f"ORB: {orb['fundamental_inliers']}  ·  SIFT: {sift['fundamental_inliers']} "
            "совпадений после эпиполярной проверки"
        )
        draw.text((48, y + 371), info, font=ImageFont.truetype(reg, 18), fill="#c6d6e7")
    draw.text(
        (45, 1500),
        "Совпадения между двумя кадрами не подтверждают правильную 3D-позу и путь.",
        font=ImageFont.truetype(reg, 18),
        fill="#e2b77d",
    )
    image.save(output, optimize=True)
    print(output.resolve())


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("report", type=Path)
    p.add_argument("images", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    run(a.report, a.images, a.output)
