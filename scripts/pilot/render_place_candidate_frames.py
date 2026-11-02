"""Visual evidence for one ambiguous same-recording retrieval."""

import hashlib
import json
from pathlib import Path

import av
from PIL import Image, ImageDraw, ImageFont


def render(base: Path):
    report = json.loads(
        (base / "visual-place-multicandidate-diverse-v2/report.json").read_text("utf-8")
    )
    row = next(row for row in report["multi_candidate"]["samples"] if row["state"] == "ambiguous")
    indices = [
        row["frame"],
        *(report["reference_frames"][index] for index in row["candidate_indices"]),
    ]
    if len(indices) != 3 or len(set(indices)) != 3 or report["physical_actions"] != 0:
        raise ValueError("unexpected_candidate_evidence")
    source = base / "source/video.h264"
    with source.open("rb") as stream:
        before = hashlib.file_digest(stream, "sha256").hexdigest()
    if before != report["source_sha256"]:
        raise ValueError("source_changed")
    frames = {}
    with av.open(str(source)) as video:
        for index, frame in enumerate(video.decode(video=0)):
            if index in indices:
                frames[index] = frame.to_image()
            if len(frames) == len(indices):
                break
    if set(frames) != set(indices):
        raise ValueError("frame_missing")
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != before:
            raise ValueError("source_changed")
    image = Image.new("RGB", (1440, 650), "#091321")
    draw = ImageDraw.Draw(image)

    def font(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", n)

    def bold(n):
        return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", n)

    draw.text((48, 32), "Одна сцена — два кандидата", font=bold(36), fill="#eff5ff")
    draw.text(
        (48, 84),
        "Разные кадры той же записи; это не независимая поездка и не проверка позы.",
        font=font(19),
        fill="#a8bad1",
    )
    titles = [
        f"Запрос · {row['seconds']:.2f} с",
        *(
            f"Кандидат · {report['reference_times'][index]:.2f} с · {n} совпадений"
            for index, n in zip(row["candidate_indices"], row["candidate_inliers"])
        ),
    ]
    for pos, index in enumerate(indices):
        x = 48 + pos * 464
        frame = frames[index].copy()
        frame.thumbnail((448, 252), Image.Resampling.LANCZOS)
        draw.rounded_rectangle(
            (x, 143, x + 448, 445), radius=12, fill="#142338", outline="#304762", width=2
        )
        image.paste(frame, (x, 143))
        draw.text((x + 10, 410), titles[pos], font=font(17), fill="#e9f2ff")
    draw.text(
        (48, 488),
        "Слабый кандидат отличается по времени записи; является ли он реальным другим местом, не установлено.",
        font=font(19),
        fill="#f5d7a1",
    )
    draw.text(
        (48, 527),
        "Алгоритм показывает неоднозначность; количество совпадений не является вероятностью правильного ответа.",
        font=font(19),
        fill="#a8bad1",
    )
    out = base / "visual-place-ambiguous-frames-v2.png"
    if out.exists():
        raise ValueError("output_exists")
    image.save(out)


if __name__ == "__main__":
    render(Path(".local-pilot/fuflo228-20261027"))
