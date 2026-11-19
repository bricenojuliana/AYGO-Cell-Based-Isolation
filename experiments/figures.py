#!/usr/bin/env python3
"""Paper and slide figures from results/runs.csv, timeline.csv and victims_by_minute.csv."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

R = Path(__file__).resolve().parents[1] / "results"
OUT = R / "figures"
COLOR = {"P": "#B42318", "C": "#1F5F99", "CIA": "#2E8B57"}
LABEL = {"P": "Pool", "C": "Celdas", "CIA": "Celdas + IA"}
INK, MUTED, GRID = "#1a1a1a", "#6b6b6b", "#e6e6e6"
FAULT = (2, 7)  # minutes 2-7 of the run (120-420 s)

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False})


def _frame(ax, ylabel, ymax):
    ax.axvspan(*FAULT, color="#000000", alpha=0.06, lw=0)
    ax.text((FAULT[0] + FAULT[1]) / 2, ymax * 0.97, "falla", ha="center", va="top", color=MUTED, fontsize=10)
    ax.set_xlim(1, 8)
    ax.set_xticks(range(1, 9))
    ax.set_ylim(-ymax * 0.03, ymax)
    ax.set_xlabel("minuto de la corrida")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def _line(ax, x, y, cfg, label_y=None):
    ax.plot(x, y, color=COLOR[cfg], lw=2.2, marker="o", ms=5, mec="white", mew=1.2)
    ax.text(x.iloc[-1] + 0.12, label_y if label_y is not None else y.iloc[-1], LABEL[cfg], color=INK, va="center", fontsize=10)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    tl = pd.read_csv(R / "timeline.csv")
    tl = tl[tl["window"] >= 1]
    tl["config"] = tl["run"].str.split("-").str[0]
    tl["scenario"] = tl["run"].str.split("-").str[1]
    vm = pd.read_csv(R / "victims_by_minute.csv").rename(columns={"w": "window"})
    vm = vm[vm["window"] >= 1]
    vm["config"] = vm["run"].str.split("-").str[0]
    vm["scenario"] = vm["run"].str.split("-").str[1]

    # 1. E1: % neighbours affected per minute
    fig, ax = plt.subplots(figsize=(8, 4.2))
    e1 = tl[tl.scenario == "E1"]
    offsets = {"P": 6, "C": None, "CIA": -2}
    for cfg in ("P", "C", "CIA"):
        g = e1[e1.config == cfg].groupby("window")["affected_pct"].median()
        g = g[g.index <= 7]
        x = pd.Series(g.index + 0.5, index=g.index)
        _line(ax, x, g, cfg, offsets[cfg])
    _frame(ax, "% de tenants vecinos afectados", 100)
    ax.set_xlim(1, 8.9)
    fig.tight_layout()
    fig.savefig(OUT / "e1_afectados_por_minuto.png", dpi=220)
    plt.close(fig)

    # 2. E1: neighbours' p99 per minute
    fig, ax = plt.subplots(figsize=(8, 4.2))
    for cfg, ly in (("P", 0.36), ("C", 0.2), ("CIA", 0.04)):
        g = vm[(vm.scenario == "E1") & (vm.config == cfg)].groupby("window")["p99"].median()
        g = g[g.index <= 7]
        _line(ax, pd.Series(g.index + 0.5, index=g.index), g / 1000, cfg, ly)
    _frame(ax, "p99 de los vecinos (s)", 2.6)
    ax.axhline(0.5, color=MUTED, lw=1, ls=(0, (4, 3)))
    ax.text(1.05, 0.55, "SLO 500 ms", color=MUTED, fontsize=9)
    ax.set_xlim(1, 8.9)
    fig.tight_layout()
    fig.savefig(OUT / "e1_p99_vecinos.png", dpi=220)
    plt.close(fig)

    # 3. Peak % affected by scenario and configuration
    runs = pd.read_csv(R / "runs.csv")
    scen = [("E0", "Sin falla (E0)"), ("E1", "Tenant ruidoso 50× (E1)"), ("E4", "Celda caída (E4)")]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    width = 0.26
    for i, (s, _) in enumerate(scen):
        for j, cfg in enumerate(("P", "C", "CIA")):
            v = runs[(runs.scenario == s) & (runs.config == cfg)]["affected_mean_pct"]
            x = i + (j - 1) * width
            if v.empty:
                if not (s == "E4" and cfg == "CIA") and not (s == "E0" and cfg == "CIA"):
                    ax.text(x, 3, "sin\ndatos", ha="center", va="bottom", fontsize=8, color=MUTED)
                continue
            ax.bar(x, v.median(), width - 0.04, color=COLOR[cfg], label=LABEL[cfg] if i == 1 else None)
            ax.text(x, v.median() + 2, f"{v.median():.0f} %", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(range(len(scen)), [t for _, t in scen])
    ax.set_xlim(-0.5, 2.5)
    ax.set_ylabel("% de vecinos afectados\n(media durante la falla)")
    ax.set_ylim(0, 112)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(OUT / "afectados_por_escenario.png", dpi=220)
    plt.close(fig)
    print(sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
