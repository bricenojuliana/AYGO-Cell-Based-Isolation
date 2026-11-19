"""Offline comparison of the online z-score detector with Isolation Forest (ADR-006) on the same windows.

Input: the FEATURES records the control loop saved (one per minute, every tenant) and the run metadata.
A tenant-window is a positive when it is the injected noisy tenant inside an E1 fault interval.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

FEATURES = ["rps", "cu", "share"]
WINDOW_S = 60


def windows_frame(feature_records: list[dict]) -> pd.DataFrame:
    rows = []
    for rec in feature_records:
        start = pd.Timestamp(rec["sk"]).timestamp()
        for tenant, w in rec.get("tenants", {}).items():
            rows.append({"start": start, "tenant": tenant, "rps": float(w["rps"]), "cu": float(w["cu"]),
                         "share": float(w["share"]), "z": float(w["score"]), "ready": bool(w["ready"])})
    return pd.DataFrame(rows)


def label(frame: pd.DataFrame, runs: list[dict]) -> pd.DataFrame:
    """Positive: noisy tenant, window fully inside the fault. Windows straddling the fault edges are dropped."""
    frame = frame.copy()
    frame["label"] = 0
    in_some_run = pd.Series(False, index=frame.index)  # trial runs and idle time are not evaluated
    for run in runs:
        end = run.get("ended_at", run["started_at"] + run.get("duration_s", 480))
        in_some_run |= (frame["start"] >= run["started_at"]) & (frame["start"] + WINDOW_S <= end)
    keep = in_some_run.copy()
    for run in runs:
        if run.get("scenario") != "E1" or not run.get("noisy_tenant"):
            continue
        lo, hi = run["started_at"] + run["fault_start_s"], run["started_at"] + run["fault_end_s"]
        mine = frame["tenant"] == run["noisy_tenant"]
        inside = (frame["start"] >= lo) & (frame["start"] + WINDOW_S <= hi)
        edge = (frame["start"] + WINDOW_S > lo) & (frame["start"] < hi) & ~inside
        frame.loc[mine & inside, "label"] = 1
        keep &= ~(mine & edge)
    return frame[keep & frame["ready"]].reset_index(drop=True)


def relative(frame: pd.DataFrame) -> np.ndarray:
    """Each feature divided by the tenant's own median, so tenants of different size are comparable."""
    med = frame.groupby("tenant")[FEATURES].transform("median").replace(0, np.nan)
    return (frame[FEATURES] / med).fillna(0.0).to_numpy()


@dataclass
class Result:
    detector: str
    precision: float
    recall: float
    f1: float
    roc_auc: float
    positives: int
    windows: int


def evaluate(frame: pd.DataFrame, z_threshold: float = 3.0, seed: int = 0) -> list[Result]:
    y = frame["label"].to_numpy()
    forest = IsolationForest(n_estimators=200, contamination="auto", random_state=seed).fit(relative(frame))
    if_score = -forest.score_samples(relative(frame))  # higher = more anomalous
    if_pred = (forest.predict(relative(frame)) == -1).astype(int)
    z_pred = (frame["z"] > z_threshold).astype(int).to_numpy()

    def result(name, pred, score):
        auc = roc_auc_score(y, score) if 0 < y.sum() < len(y) else float("nan")
        return Result(name, round(precision_score(y, pred, zero_division=0), 3), round(recall_score(y, pred), 3),
                      round(f1_score(y, pred, zero_division=0), 3), round(auc, 3), int(y.sum()), len(y))

    return [result(f"z-score EWMA (z > {z_threshold})", z_pred, frame["z"].to_numpy()),
            result("Isolation Forest", if_pred, if_score)]
