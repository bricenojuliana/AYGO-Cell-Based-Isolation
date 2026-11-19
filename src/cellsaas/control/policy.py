"""Turns scores into actions (SPEC 5.4 IsolationPolicy). Pure logic: no AWS."""
from __future__ import annotations

from collections.abc import Mapping

from ..routing import Route
from .model import Baseline, CellHealth, Decision, Score


class IsolationPolicy:
    """Quarantine a tenant only when (1) its demand is anomalous for `k` consecutive windows and
    (2) its cell shows symptoms. At most one tenant per cell per cycle (the highest score), so the
    loop cannot empty a cell by mistake; already quarantined tenants are left alone."""

    def __init__(self, threshold: float = 3.0, k: int = 2, slo_p99_ms: float = 500.0, max_bad_ratio: float = 0.01):
        self.threshold = threshold
        self.k = k
        self._slo = slo_p99_ms
        self._max_bad = max_bad_ratio

    def update_streaks(self, scores: Mapping[str, Score], baselines: Mapping[str, Baseline]) -> None:
        for tenant_id, score in scores.items():
            baseline = baselines[tenant_id]
            baseline.streak = baseline.streak + 1 if self.is_anomalous(score) else 0

    def is_anomalous(self, score: Score) -> bool:
        return score.ready and score.value > self.threshold

    def should_learn(self, score: Score, route: Route | None, cells: Mapping[str, CellHealth]) -> bool:
        """The baseline learns only from normal behaviour: the tenant is not anomalous and its cell is healthy.
        A victim's demand drops while its cell is saturated; learning that would make its recovery look anomalous."""
        if self.is_anomalous(score):
            return False
        health = cells.get(route.cell_id) if route else None
        return health is None or not health.symptomatic(self._slo, self._max_bad)

    def decide(self, scores: Mapping[str, Score], baselines: Mapping[str, Baseline],
               cells: Mapping[str, CellHealth], routes: Mapping[str, Route], act: bool) -> list[Decision]:
        handled = {r.home_cell_id for r in routes.values() if r.quarantined}
        best_per_cell: dict[str, Score] = {}
        for tenant_id, score in scores.items():
            route = routes.get(tenant_id)
            if route is None or route.quarantined or baselines[tenant_id].streak < self.k or route.cell_id in handled:
                continue
            current = best_per_cell.get(route.cell_id)
            if current is None or score.value > current.value:
                best_per_cell[route.cell_id] = score
        decisions = []
        for cell_id, score in sorted(best_per_cell.items()):
            health = cells.get(cell_id)
            if health is None or not health.symptomatic(self._slo, self._max_bad):
                continue
            decisions.append(Decision(
                tenant_id=score.tenant_id, action="QUARANTINE" if act else "OBSERVE", from_cell=cell_id,
                score=score.value, feature=score.feature,
                reason=f"{score.feature} z={score.value} > {self.threshold} for {baselines[score.tenant_id].streak} "
                       f"windows and cell {cell_id} is degraded",
            ))
        return decisions
