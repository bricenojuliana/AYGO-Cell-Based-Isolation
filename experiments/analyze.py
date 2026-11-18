#!/usr/bin/env python3
"""Turns results/raw into tables and figures for the paper (results/).

  python3 experiments/analyze.py                 # results/raw -> results/{runs.csv,summary.csv,tests.csv,*.png}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import mannwhitneyu  # noqa: E402

from experiments.cellexp.metrics import affected_timeline, asdict, cliffs_delta, load_requests, run_metrics  # noqa: E402

LABEL = {"P": "Pool", "C": "Celdas", "CIA": "Celdas + IA"}
COLOR = {"P": "#b2182b", "C": "#2166ac", "CIA": "#1b7837"}
METRICS = ["affected_peak_pct", "affected_mean_pct", "p99_ms", "error_pct", "mttr_s"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", type=Path, default=ROOT / "results" / "raw")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rows, timelines = [], []
    for meta_path in sorted(args.raw.glob("*.json")):
        meta = json.loads(meta_path.read_text())
        df = load_requests(meta_path.with_suffix(".csv"), meta["started_at"])
        rows.append(asdict(run_metrics(df, meta)))
        tl = affected_timeline(df, meta).rename("affected_pct").reset_index()
        tl["config"], tl["scenario"], tl["rep"] = meta["config"], meta["scenario"], meta["rep"]
        timelines.append(tl)
    if not rows:
        sys.exit(f"no runs in {args.raw}")
    runs = pd.DataFrame(rows).sort_values(["scenario", "config", "rep"])
    runs.to_csv(args.out / "runs.csv", index=False)

    summary = runs.groupby(["scenario", "config"])[METRICS + ["mttd_s", "routing_overhead_p50_ms"]].agg(
        ["median", "min", "max"]).round(1)
    summary.to_csv(args.out / "summary.csv")

    tests = []
    for scenario, group in runs.groupby("scenario"):
        configs = sorted(group["config"].unique())
        for i, a in enumerate(configs):
            for b in configs[i + 1:]:
                for metric in ("affected_peak_pct", "affected_mean_pct", "p99_ms", "mttr_s"):
                    x = group[group.config == a][metric].dropna()
                    y = group[group.config == b][metric].dropna()
                    if len(x) and len(y) and (x.nunique() > 1 or y.nunique() > 1 or x.iloc[0] != y.iloc[0]):
                        p = mannwhitneyu(x, y, alternative="two-sided").pvalue
                    else:
                        p = float("nan")
                    tests.append({"scenario": scenario, "metric": metric, "a": a, "b": b, "n_a": len(x), "n_b": len(y),
                                  "median_a": x.median(), "median_b": y.median(), "p_value": p,
                                  "cliffs_delta": round(cliffs_delta(x, y), 2)})
    pd.DataFrame(tests).to_csv(args.out / "tests.csv", index=False)

    timeline = pd.concat(timelines)
    for scenario, group in timeline.groupby("scenario"):
        meta_any = json.loads(next(args.raw.glob(f"*-{scenario}-*.json")).read_text())
        fig, ax = plt.subplots(figsize=(7, 3.6))
        for config, g in group.groupby("config"):
            med = g.groupby("window")["affected_pct"].median()
            ax.plot(med.index + 0.5, med.values, marker="o", ms=3, lw=2, color=COLOR[config], label=LABEL[config])
        ax.axvspan(meta_any["fault_start_s"] / 60, meta_any["fault_end_s"] / 60, color="#999999", alpha=0.15,
                   label="falla")
        ax.set(xlabel="minuto de la corrida", ylabel="% de tenants vecinos afectados", ylim=(-3, 103),
               title=f"Escenario {scenario}: tenants afectados por minuto (mediana de repeticiones)")
        ax.grid(alpha=0.3)
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(args.out / f"timeline_{scenario}.png", dpi=200)
        plt.close(fig)

    for metric, ylabel in (("affected_peak_pct", "% afectados (peor minuto)"), ("p99_ms", "p99 de vecinos (ms)")):
        fig, ax = plt.subplots(figsize=(7, 3.6))
        labels, data, colors = [], [], []
        for (scenario, config), g in runs.groupby(["scenario", "config"]):
            labels.append(f"{scenario}\n{LABEL[config]}")
            data.append(g[metric].dropna().values)
            colors.append(COLOR[config])
        box = ax.boxplot(data, patch_artist=True, widths=0.6)
        ax.set_xticks(range(1, len(labels) + 1), labels, fontsize=8)
        for patch, color in zip(box["boxes"], colors, strict=True):
            patch.set(facecolor=color, alpha=0.5)
        ax.set(ylabel=ylabel)
        ax.grid(axis="y", alpha=0.3)
        fig.tight_layout()
        fig.savefig(args.out / f"box_{metric}.png", dpi=200)
        plt.close(fig)
    print(runs.to_string(index=False))


if __name__ == "__main__":
    main()
