"""The control loop, run once a minute (SPEC RF08-RF10): read -> score -> decide -> isolate -> audit -> learn."""
from __future__ import annotations

import time
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Protocol

from ..routing import Route
from .detector import AnomalyDetector, scores_by_tenant
from .metrics import MetricsSource
from .model import Baseline
from .policy import IsolationPolicy
from .store import DynamoControlStore

MODES = ("off", "observe", "act")


class Router(Protocol):
    def routes(self) -> list[Route]: ...

    def quarantine(self, tenant_id: str, quarantine_cell_id: str) -> bool: ...


class ControlLoop:
    def __init__(self, routing: Router, metrics: MetricsSource, detector: AnomalyDetector, policy: IsolationPolicy,
                 store: DynamoControlStore, quarantine_cell: str = "q", lag_seconds: int = 60):
        self._routing = routing
        self._metrics = metrics
        self._detector = detector
        self._policy = policy
        self._store = store
        self._quarantine_cell = quarantine_cell
        self._lag = lag_seconds

    def run(self, now: datetime, mode: str) -> dict:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if mode == "off":
            return {"mode": mode}
        # Last closed minute, `lag` seconds back so CloudWatch has ingested the EMF records.
        end = now.replace(second=0, microsecond=0) - timedelta(seconds=self._lag)
        start = end - timedelta(minutes=1)
        routes = {r.tenant_id: r for r in self._routing.routes()}
        windows, cells = self._metrics.read(start, end, routes)
        baselines = self._store.load_baselines()
        for tenant_id in windows:
            baselines.setdefault(tenant_id, Baseline())
        scores = scores_by_tenant(self._detector, windows, baselines)
        self._policy.update_streaks(scores, baselines)
        decisions = self._policy.decide(scores, baselines, cells, routes, act=(mode == "act"))

        now_iso = now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for decision in decisions:
            started = time.monotonic()
            applied = (decision.action == "QUARANTINE"
                       and self._routing.quarantine(decision.tenant_id, self._quarantine_cell))
            self._store.append_audit(now_iso, {
                "tenantId": decision.tenant_id, "action": decision.action, "applied": applied,
                "fromCell": decision.from_cell, "toCell": self._quarantine_cell if applied else decision.from_cell,
                "score": decision.score, "feature": decision.feature, "threshold": self._policy.threshold,
                "k": self._policy.k, "reason": decision.reason, "windowStart": start.isoformat(),
                "durationMs": round((time.monotonic() - started) * 1000, 1), "mode": mode, "actor": "detector",
            })

        for tenant_id, window in windows.items():
            if not self._policy.is_anomalous(scores[tenant_id]):
                self._detector.learn(window, baselines[tenant_id])
        self._store.save_baselines(baselines)
        self._store.save_features(start.isoformat(), {
            "mode": mode,
            "tenants": {t: {**asdict(w), "score": scores[t].value, "ready": scores[t].ready,
                            "streak": baselines[t].streak} for t, w in windows.items()},
            "cells": {c: asdict(h) for c, h in cells.items()},
        })
        return {"mode": mode, "window": start.isoformat(), "tenants": len(windows),
                "decisions": [asdict(d) for d in decisions]}
