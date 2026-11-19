"""Run-level metrics from the client-side request log (SPEC 7). Pure pandas: unit-tested on synthetic runs."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

WINDOW_S = 60
SLO_P99_MS = 500.0
MAX_BAD_RATIO = 0.01


def load_requests(csv_path, started_at: float) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["t"] = df["sent_at"] - started_at
    df["bad"] = (df["status"] == 0) | (df["status"] >= 500) | (df["status"] == 429)
    df["window"] = (df["t"] // WINDOW_S).astype(int)
    return df


def tenant_windows(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (tenant, window): requests, bad ratio, p99 and whether the tenant was affected (SPEC 2)."""
    grouped = df.groupby(["tenant", "window"])
    out = pd.DataFrame({
        "requests": grouped.size(),
        "bad_ratio": grouped["bad"].mean(),
        "p99_ms": grouped["latency_ms"].quantile(0.99),
    }).reset_index()
    out["affected"] = (out["p99_ms"] > SLO_P99_MS) | (out["bad_ratio"] > MAX_BAD_RATIO)
    return out


@dataclass
class RunMetrics:
    run: str
    config: str
    scenario: str
    rep: int
    victims: int
    affected_peak_pct: float  # worst minute during the fault
    affected_mean_pct: float  # mean over fault minutes
    p50_ms: float
    p95_ms: float
    p99_ms: float
    error_pct: float
    requests: int
    mttd_s: float | None  # detector decision - fault start (C+IA only)
    mttr_s: float | None  # victims back in SLO for 2 windows - fault start; None if never during the run
    routing_overhead_p50_ms: float | None
    false_quarantines: int  # applied quarantines of tenants that were not the injected noisy one


def run_metrics(df: pd.DataFrame, meta: dict) -> RunMetrics:
    start_w = int(meta["fault_start_s"] // WINDOW_S)
    end_w = int(np.ceil(meta["fault_end_s"] / WINDOW_S))
    victims_df = df[df["tenant"] != meta.get("noisy_tenant")]
    windows = tenant_windows(victims_df)
    victims = victims_df["tenant"].nunique()
    per_window = windows.groupby("window")["affected"].sum() / max(victims, 1) * 100
    fault = per_window[(per_window.index >= start_w) & (per_window.index < end_w)]
    in_fault = victims_df[(victims_df["t"] >= meta["fault_start_s"]) & (victims_df["t"] < meta["fault_end_s"])]
    ok = in_fault[~in_fault["bad"]]["latency_ms"]

    mttd = None
    applied = [a for a in meta.get("audit", []) if a.get("action") == "QUARANTINE" and a.get("applied")]
    hits = [a for a in applied if a.get("tenantId") == meta.get("noisy_tenant")]
    if hits:
        decided = pd.Timestamp(hits[0]["sk"].split("#")[0]).timestamp()
        mttd = round(decided - (meta["started_at"] + meta["fault_start_s"]), 1)

    mttr = None
    later = per_window[per_window.index >= start_w]
    healthy = later == 0
    if not fault.empty and fault.max() > 0:
        for w in later.index[:-1]:
            if healthy.get(w, False) and healthy.get(w + 1, False) and w > start_w:
                mttr = float(w * WINDOW_S - meta["fault_start_s"])
                break
    else:
        mttr = 0.0

    overhead = None
    if "cell_ms" in df and df["cell_ms"].notna().any():
        normal = df[(~df["bad"]) & df["cell_ms"].notna() & (df["t"] < meta["fault_start_s"])]
        if not normal.empty:
            overhead = round(float((normal["latency_ms"] - normal["cell_ms"]).median()), 1)

    return RunMetrics(
        run=meta["run"], config=meta["config"], scenario=meta["scenario"], rep=meta["rep"], victims=victims,
        affected_peak_pct=round(float(fault.max()) if not fault.empty else 0.0, 1),
        affected_mean_pct=round(float(fault.mean()) if not fault.empty else 0.0, 1),
        p50_ms=round(float(ok.quantile(0.5)), 1) if len(ok) else float("nan"),
        p95_ms=round(float(ok.quantile(0.95)), 1) if len(ok) else float("nan"),
        p99_ms=round(float(ok.quantile(0.99)), 1) if len(ok) else float("nan"),
        error_pct=round(float(in_fault["bad"].mean() * 100), 2) if len(in_fault) else 0.0,
        requests=len(df), mttd_s=mttd, mttr_s=mttr, routing_overhead_p50_ms=overhead,
        false_quarantines=len(applied) - len(hits),
    )


def affected_timeline(df: pd.DataFrame, meta: dict) -> pd.Series:
    victims_df = df[df["tenant"] != meta.get("noisy_tenant")]
    windows = tenant_windows(victims_df)
    return windows.groupby("window")["affected"].sum() / max(victims_df["tenant"].nunique(), 1) * 100


def cliffs_delta(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if not len(a) or not len(b):
        return float("nan")
    gt = sum((x > y) for x in a for y in b)
    lt = sum((x < y) for x in a for y in b)
    return (gt - lt) / (len(a) * len(b))


__all__ = ["RunMetrics", "run_metrics", "affected_timeline", "cliffs_delta", "asdict"]
