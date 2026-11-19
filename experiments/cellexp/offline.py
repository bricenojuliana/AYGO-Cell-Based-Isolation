"""Offline comparison of the online z-score detector with Isolation Forest (ADR-006) on the same windows.

Input: either the FEATURES records the control loop saved (one per minute, every tenant) and the run metadata,
or the client-side tenant-minutes the load generator recorded (`client_frame`).
A tenant-window is a positive when it is the injected noisy tenant inside an E1 fault interval.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from cellsaas.control.detector import ZScoreDetector
from cellsaas.control.model import Baseline

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
        if not run.get("noisy_tenant"):
            continue
        lo, hi = run["started_at"] + run["fault_start_s"], run["started_at"] + run["fault_end_s"]
        mine = frame["tenant"] == run["noisy_tenant"]
        inside = (frame["start"] >= lo) & (frame["start"] + WINDOW_S <= hi)
        edge = (frame["start"] + WINDOW_S > lo) & (frame["start"] < hi) & ~inside
        frame.loc[mine & inside, "label"] = 1
        keep &= ~(mine & edge)
    return frame[keep & frame["ready"]].reset_index(drop=True)


CLIENT_FEATURES = ["rps", "share"]
LOAD_WINDOWS = 8  # 480 s of load; a later window is a partial tail


@dataclass(frozen=True)
class _Window:
    """Duck-typed TenantWindow: the client only sees offered demand."""
    tenant_id: str
    rps: float
    share: float

    def feature(self, name: str) -> float:
        return float(getattr(self, name))


def client_frame(minutes: pd.DataFrame, z_threshold: float = 3.0) -> pd.DataFrame:
    """Tenant-minutes seen by the load generator -> the same frame `evaluate` takes.

    rps is the offered rate and share the tenant's fraction of all requests in that minute. The z-score is
    replayed with the production ZScoreDetector, one baseline per tenant carried across runs in time order,
    learning only from non-anomalous windows (ADR-010). Window 0 of each run (cold starts) and partial tail
    windows after the load are dropped.
    """
    df = minutes[(minutes["w"] > 0) & (minutes["w"] < LOAD_WINDOWS)].copy()
    df["rps"] = df["sent"] / WINDOW_S
    df["share"] = df["sent"] / df.groupby(["run", "w"])["sent"].transform("sum")
    df = df.sort_values(["start", "tenant"]).reset_index(drop=True)
    detector, baselines, z, ready = ZScoreDetector(features=tuple(CLIENT_FEATURES)), {}, [], []
    for row in df.itertuples():
        base = baselines.setdefault(row.tenant, Baseline())
        window = _Window(row.tenant, row.rps, row.share)
        score = detector.score(window, base)
        z.append(score.value)
        ready.append(score.ready)
        if score.value <= z_threshold:
            detector.learn(window, base)
    df["z"], df["ready"] = z, ready
    return df[df["ready"]].reset_index(drop=True)


def relative(frame: pd.DataFrame, features: list[str] = FEATURES) -> np.ndarray:
    """Each feature divided by the tenant's own median, so tenants of different size are comparable."""
    med = frame.groupby("tenant")[features].transform("median").replace(0, np.nan)
    return (frame[features] / med).fillna(0.0).to_numpy()


@dataclass
class Result:
    detector: str
    precision: float
    recall: float
    f1: float
    roc_auc: float
    positives: int
    windows: int


def evaluate(frame: pd.DataFrame, z_threshold: float = 3.0, seed: int = 0,
             features: list[str] = FEATURES) -> list[Result]:
    y = frame["label"].to_numpy()
    x = relative(frame, features)
    forest = IsolationForest(n_estimators=200, contamination="auto", random_state=seed).fit(x)
    if_score = -forest.score_samples(x)  # higher = more anomalous
    if_pred = (forest.predict(x) == -1).astype(int)
    z_pred = (frame["z"] > z_threshold).astype(int).to_numpy()

    def result(name, pred, score):
        auc = roc_auc_score(y, score) if 0 < y.sum() < len(y) else float("nan")
        return Result(name, round(precision_score(y, pred, zero_division=0), 3), round(recall_score(y, pred), 3),
                      round(f1_score(y, pred, zero_division=0), 3), round(auc, 3), int(y.sum()), len(y))

    return [result(f"z-score EWMA (z > {z_threshold})", z_pred, frame["z"].to_numpy()),
            result("Isolation Forest", if_pred, if_score)]
