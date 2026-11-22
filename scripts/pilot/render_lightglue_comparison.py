"""Visualize offline per-frame correspondence/PnP diagnostics."""

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

    report = json.loads(a.report.read_text(encoding="utf-8"))
    samples = report["samples"]
    if not samples or a.output.exists():
        raise ValueError("visualization_input_or_output_invalid")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(13.4, 4.5), facecolor="#0e1627")
    ax.set_facecolor("#131e31")
    for y, label, prefix in [(1, "RootSIFT", "baseline"), (0, "RootSIFT + LightGlue", "lightglue")]:
        colors = [
            "#f27782"
            if not s[prefix + "_pnp"]
            else "#ffd16b"
            if s[prefix + "_ambiguous"]
            else "#59d8b1"
            for s in samples
        ]
        ax.scatter(
            [s["seconds"] for s in samples],
            [y] * len(samples),
            c=colors,
            s=56,
            edgecolors="#0e1627",
            linewidths=0.7,
        )
        ax.text(
            max(s["seconds"] for s in samples) + 0.3,
            y,
            f"{sum(s[prefix + '_unambiguous_candidate'] for s in samples)} / {len(samples)}",
            color="#dbe6f5",
            va="center",
        )
    for c, label in [
        ("#59d8b1", "PnP без конфликта"),
        ("#ffd16b", "конфликт поз"),
        ("#f27782", "нет оценки"),
    ]:
        ax.scatter([], [], color=c, s=55, label=label)
    times = [s["seconds"] for s in samples]
    ax.set_xlim(min(times) - 0.2, max(times) + 1.1)
    ax.set_ylim(-0.55, 1.6)
    ax.set_yticks([1, 0], ["RootSIFT", "RootSIFT + LightGlue"], color="#dbe6f5")
    ax.tick_params(axis="x", colors="#b6c4d9")
    ax.set_xlabel("Время исходной записи, с", color="#b6c4d9")
    ax.grid(axis="x", color="#72819a", alpha=0.17)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, frameon=False, labelcolor="#dbe6f5"
    )
    fig.text(
        0.06,
        0.94,
        "fuflo228 · сопоставление и проверка поз",
        color="#f1f5fc",
        fontsize=19,
        weight="bold",
    )
    fig.text(
        0.06,
        0.88,
        f"{len(samples)} одинаковых кадров из той же записи · пять одинаковых кандидатов",
        color="#b6c4d9",
        fontsize=10,
    )
    fig.text(
        0.06,
        0.035,
        "Оценки отдельных кадров: ни точность в метрах, ни самостоятельная езда не подтверждены.",
        color="#9eb0c9",
        fontsize=9,
    )
    fig.subplots_adjust(left=0.21, right=0.91, top=0.76, bottom=0.26)
    fig.savefig(a.output, dpi=150, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
