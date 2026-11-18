"""Anomaly detectors behind one interface (ADR-006, QAS08: a new detector is one new class)."""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping

from .model import DEMAND_FEATURES, Baseline, Score, TenantWindow


class AnomalyDetector(ABC):
    @abstractmethod
    def score(self, window: TenantWindow, baseline: Baseline) -> Score:
        """Anomaly score of this tenant window against the tenant's baseline."""

    @abstractmethod
    def learn(self, window: TenantWindow, baseline: Baseline) -> None:
        """Updates the baseline with a window judged normal."""


class ZScoreDetector(AnomalyDetector):
    """Per-tenant EWMA baseline; score = max z over demand features (SPEC 6).

    `min_std_ratio` and `min_std` put a floor under the standard deviation so a very steady tenant
    does not turn small wiggles into huge z values.
    """

    def __init__(self, alpha: float = 0.1, warmup_windows: int = 5, min_std_ratio: float = 0.1, min_std: float = 0.2,
                 features: tuple[str, ...] = DEMAND_FEATURES):
        self._alpha = alpha
        self._warmup = warmup_windows
        self._min_std_ratio = min_std_ratio
        self._min_std = min_std
        self._features = features

    def score(self, window: TenantWindow, baseline: Baseline) -> Score:
        if baseline.windows < self._warmup:
            return Score(window.tenant_id, 0.0, "", ready=False)
        best, best_feature = -math.inf, ""
        for name in self._features:
            mean = baseline.mean.get(name, 0.0)
            std = max(math.sqrt(baseline.var.get(name, 0.0)), self._min_std_ratio * abs(mean), self._min_std)
            z = (window.feature(name) - mean) / std
            if z > best:
                best, best_feature = z, name
        return Score(window.tenant_id, round(best, 3), best_feature, ready=True)

    def learn(self, window: TenantWindow, baseline: Baseline) -> None:
        for name in self._features:
            x = window.feature(name)
            if baseline.windows == 0:
                baseline.mean[name], baseline.var[name] = x, 0.0
                continue
            mean = baseline.mean.get(name, x)
            delta = x - mean
            new_mean = mean + self._alpha * delta
            baseline.var[name] = (1 - self._alpha) * (baseline.var.get(name, 0.0) + self._alpha * delta * delta)
            baseline.mean[name] = new_mean
        baseline.windows += 1


def scores_by_tenant(detector: AnomalyDetector, windows: Mapping[str, TenantWindow],
                     baselines: Mapping[str, Baseline]) -> dict[str, Score]:
    return {t: detector.score(w, baselines.get(t) or Baseline()) for t, w in windows.items()}
