"""Plot measured same-recording camera disagreements after alignment."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path)
    a = parser.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    report = json.loads(a.report.read_text(encoding="utf-8"))
    rows = report["heldout_rows"]
    if not rows or a.output.exists():
        raise ValueError("orientation_plot_input_or_output")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(13.4, 6.5), sharex=True, facecolor="#0e1627")
    x = [r["seconds"] for r in rows]
    for ax, key, color, label in (
        (top, "center_disagreement_steps", "#ffcb6b", "Центр камеры · шаги модели"),
        (bottom, "orientation_disagreement_degrees", "#65d9bc", "Ориентация · градусы"),
    ):
        ax.set_facecolor("#131e31")
        ax.plot(x, [r[key] for r in rows], color=color, linewidth=2.2, marker="o", markersize=4)
        ax.set_ylabel(label, color="#b6c4d9")
        ax.tick_params(colors="#b6c4d9")
        ax.grid(color="#72819a", alpha=0.17)
        for spine in ax.spines.values():
            spine.set_visible(False)
    bottom.set_xlabel("Время исходной записи, с", color="#b6c4d9")
    fig.text(
        0.06,
        0.96,
        "fuflo228 · положение и поворот камеры",
        color="#f1f5fc",
        fontsize=19,
        weight="bold",
    )
    fig.text(
        0.06,
        0.915,
        "Модели совмещены по 13 ранним камерам; показаны 17 более поздних",
        color="#b6c4d9",
        fontsize=10,
    )
    fig.text(
        0.06,
        0.035,
        "Оси разные. Это расхождение моделей на одном видео, а не ошибка относительно истины.",
        color="#9eb0c9",
        fontsize=9,
    )
    fig.subplots_adjust(left=0.13, right=0.96, top=0.83, bottom=0.16, hspace=0.25)
    fig.savefig(a.output, dpi=150, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
