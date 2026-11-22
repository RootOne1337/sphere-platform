"""Static illustration of a synthetic test, not a real route or measurement."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    output = Path("docs/audits/2026-10-27/candidate-diversity-synthetic.png")
    image = Image.new("RGB", (1560, 590), "#0b121e")
    d = ImageDraw.Draw(image)
    regular = "C:/Windows/Fonts/segoeui.ttf"
    bold = "C:/Windows/Fonts/segoeuib.ttf"

    def font(size):
        return ImageFont.truetype(regular, size)

    def heavy(size):
        return ImageFont.truetype(bold, size)

    d.text((55, 32), "Похожий перекрёсток за пределами top-4", font=heavy(38), fill="#f1f5fc")
    d.text(
        (57, 87),
        "ИСКУССТВЕННЫЙ ТЕСТ  ·  одинаковые виды, разные места на записи",
        font=font(21),
        fill="#96aabf",
    )
    slots = [(64, 248), (350, 534), (636, 820), (922, 1106), (1208, 1392)]
    labels = [
        ("4,3 c", "участок B"),
        ("4,2 c", "участок B"),
        ("4,1 c", "участок B"),
        ("4,0 c", "участок B"),
        ("0,0 c", "участок A"),
    ]
    for y, label, selected in (
        (175, "ОБЫЧНЫЙ ПОИСК", {0, 1, 2, 3}),
        (345, "РАЗНООБРАЗНЫЕ КАНДИДАТЫ", {0, 1, 2, 4}),
    ):
        d.text((65, y - 40), label, font=heavy(18), fill="#8fe3ce")
        for i, ((x1, x2), (tick, region)) in enumerate(zip(slots, labels)):
            border = "#75ddbb" if i in selected else "#425069"
            d.rounded_rectangle((x1, y, x2, y + 108), 15, fill="#162337", outline=border, width=3)
            d.text((x1 + 15, y + 13), f"РАНГ {i + 1}", font=heavy(16), fill="#a7bad0")
            d.text((x1 + 15, y + 40), tick, font=heavy(25), fill="#f1f6ff")
            d.text(
                (x1 + 15, y + 77),
                region + (" · проверен" if i in selected else " · пропущен"),
                font=font(14),
                fill="#9fb1c4",
            )
    d.text(
        (65, 500),
        "Разнообразие кандидатов помогает увидеть конкурента, но не доказывает правильное место.",
        font=font(20),
        fill="#d4dfec",
    )
    d.text(
        (65, 536),
        "Время — позиция внутри записи, не метры; тест не является проездом.",
        font=font(18),
        fill="#8fa2b7",
    )
    image.save(output)
    print(output.resolve())


if __name__ == "__main__":
    main()
