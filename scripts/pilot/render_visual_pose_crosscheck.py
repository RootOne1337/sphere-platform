"""Render factual, same-recording 2D/3D offline cross-check results."""

import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = json.loads(a.report.read_text(encoding="utf-8"))
    rows = data["samples"]
    if not rows or a.output.exists():
        raise ValueError("crosscheck_plot_input_or_output")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(13.4, 4.8), facecolor="#0e1627")
    ax.set_facecolor("#131e31")
    ts = [r["seconds"] for r in rows]
    visual = ["#59d8b1" if r["visual_state"] == "matched" else "#f27782" for r in rows]
    pose = [
        "#f27782"
        if not r["pose_pnp"]
        else "#ffd16b"
        if r["pose_ambiguous"] or r["pose_center_jump"] is True
        else "#59d8b1"
        for r in rows
    ]
    for y, colors in ((1, visual), (0, pose)):
        ax.scatter(ts, [y] * len(ts), c=colors, s=58, edgecolors="#0e1627", linewidths=0.8)
    ax.set_yticks([1, 0], ["2D: поиск места", "3D: оценка камеры"], color="#dbe6f5")
    ax.tick_params(axis="x", colors="#b6c4d9")
    ax.set_xlabel("Время исходной записи, с", color="#b6c4d9")
    ax.set_xlim(min(ts) - 0.2, max(ts) + 0.2)
    ax.set_ylim(-0.55, 1.55)
    ax.grid(axis="x", color="#72819a", alpha=0.17)
    for spine in ax.spines.values():
        spine.set_visible(False)
    for color, label in [
        ("#59d8b1", "совпадение / оценка"),
        ("#ffd16b", "скачок или конфликт"),
        ("#f27782", "неизвестно"),
    ]:
        ax.scatter([], [], color=color, s=55, label=label)
    ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.19), ncol=3, frameon=False, labelcolor="#dbe6f5"
    )
    fig.text(
        0.06,
        0.94,
        "fuflo228 · 2D и 3D на тех же кадрах",
        color="#f1f5fc",
        fontsize=19,
        weight="bold",
    )
    fig.text(
        0.06,
        0.88,
        f"{len(rows)} общих кадров из той же записи · отсутствующие кадры не показаны",
        color="#b6c4d9",
        fontsize=10,
    )
    fig.text(
        0.06,
        0.035,
        "Сходство изображений не доказывает положение в метрах, проходимость или готовность к управлению.",
        color="#9eb0c9",
        fontsize=9,
    )
    fig.subplots_adjust(left=0.19, right=0.96, top=0.76, bottom=0.26)
    fig.savefig(a.output, dpi=150, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
