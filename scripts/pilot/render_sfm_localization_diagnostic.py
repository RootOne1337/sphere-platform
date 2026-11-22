"""Plot actual offline held-out localization states and map support."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [
        ("Базовая модель", "sfm-baseline-localization-current-v1"),
        ("Локальная модель", "sfm-tail-fixed-localization-v2"),
        ("SfM-треки", "sfm-tail-track-localization-v1"),
    ]
    reports = [
        (
            label,
            json.loads(
                (args.root / folder / "heldout-tail/report.json").read_text(encoding="utf-8")
            ),
        )
        for label, folder in names
    ]
    if any(
        [s["source_index"] for s in r["samples"]]
        != [s["source_index"] for s in reports[0][1]["samples"]]
        for _, r in reports[1:]
    ):
        raise ValueError("heldout_sample_indices_differ")
    colors = {"localized": "#59d8b1", "confirming": "#ffd16b", "unknown": "#f27782"}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(13.2, 4.8), facecolor="#0e1627")
    ax.set_facecolor("#131e31")
    for n, (label, report) in enumerate(reports):
        ax.scatter(
            [s["media_seconds"] for s in report["samples"]],
            [2 - n] * len(report["samples"]),
            c=[colors[s["pose"]["state"]] for s in report["samples"]],
            s=52,
            edgecolors="#0e1627",
            linewidths=0.7,
        )
        ax.text(
            33.5,
            2 - n,
            f"{report['counts'].get('localized', 0)} / {len(report['samples'])}",
            color="#dbe6f5",
            va="center",
        )
    for state, label in [
        ("localized", "подтверждено"),
        ("confirming", "проверяется"),
        ("unknown", "нет подтверждения"),
    ]:
        ax.scatter([], [], color=colors[state], s=55, label=label)
    ax.set_yticks([2, 1, 0], [label for label, _ in reports], color="#dbe6f5")
    ax.set_xlim(24.85, 34.35)
    ax.set_ylim(-0.58, 2.65)
    ax.set_xlabel("Время исходного видео, с", color="#b6c4d9")
    ax.tick_params(axis="x", colors="#b6c4d9")
    ax.grid(axis="x", color="#72819a", alpha=0.17)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.49, -0.18),
        ncol=3,
        frameon=False,
        labelcolor="#dbe6f5",
    )
    fig.text(
        0.065,
        0.94,
        "fuflo228 · проверка конца маршрута",
        color="#f1f5fc",
        fontsize=20,
        weight="bold",
    )
    fig.text(
        0.065,
        0.885,
        "37 одинаковых кадров из исходной записи, исключены опорные; это не новый игровой проход",
        color="#b6c4d9",
        fontsize=10,
    )
    fig.text(0.91, 0.80, "распознано", color="#9eb0c9", fontsize=9, ha="right")
    fig.text(
        0.065,
        0.035,
        "Даже «подтверждено» не доказывает точность в метрах и не разрешает управление.",
        color="#9eb0c9",
        fontsize=9,
    )
    fig.subplots_adjust(left=0.19, right=0.93, top=0.77, bottom=0.25)
    if args.output.exists():
        raise FileExistsError(args.output)
    fig.savefig(args.output, dpi=150, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
