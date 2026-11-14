"""Render saved KLT consistency measurements without altering any model."""

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
    rows = report["samples"]
    if not rows or a.output.exists():
        raise ValueError("klt_plot_input_or_output")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})
    fig, ax = plt.subplots(figsize=(13.4, 5.5), facecolor="#0e1627")
    ax.set_facecolor("#131e31")
    styles = [
        ("baseline", "Исходная", "#68b5ff"),
        ("tail_fixed", "Локальная · без уточнения фокуса в BA", "#5be0bd"),
        ("tail_optimized", "Локальная · уточнённый фокус", "#ffcb6b"),
        ("full_fixed", "Вся запись · без уточнения фокуса в BA", "#f17f8f"),
    ]
    for key, label, color in styles:
        vals = [
            (r["seconds"], r["models"][key]["median_px"])
            for r in rows
            if key in r["models"] and r["models"][key]["median_px"] is not None
        ]
        ax.plot(
            [t for t, _ in vals],
            [max(v, 0.01) for _, v in vals],
            color=color,
            label=label,
            linewidth=2,
            alpha=0.9,
        )
    ax.set_yscale("log")
    ax.set_xlabel("Время второй камеры исходной записи, с", color="#b6c4d9")
    ax.set_ylabel("Ошибка, пиксели · лог. шкала", color="#b6c4d9")
    ax.tick_params(colors="#b6c4d9")
    ax.grid(color="#72819a", alpha=0.16, which="both")
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.19),
        ncol=2,
        frameon=False,
        labelcolor="#dbe6f5",
        fontsize=9,
    )
    fig.text(
        0.06,
        0.95,
        "fuflo228 · камеры и независимые оптические треки",
        color="#f1f5fc",
        fontsize=18,
        weight="bold",
    )
    fig.text(
        0.06,
        0.895,
        "31 пара исходных кадров; одинаковые KLT-треки для четырёх вариантов модели",
        color="#b6c4d9",
        fontsize=10,
    )
    fig.text(
        0.06,
        0.025,
        "Это проверка согласованности на той же записи, а не измерение истинного пути или метров.",
        color="#9eb0c9",
        fontsize=9,
    )
    fig.subplots_adjust(left=0.12, right=0.97, top=0.79, bottom=0.30)
    fig.savefig(a.output, dpi=150, facecolor=fig.get_facecolor())


if __name__ == "__main__":
    main()
