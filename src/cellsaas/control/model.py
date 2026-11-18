"""Values exchanged inside the control plane (SPEC 6)."""
from __future__ import annotations

from dataclasses import dataclass, field

DEMAND_FEATURES = ("rps", "cu")  # attribution uses demand only, never symptoms (SPEC 6)


@dataclass(frozen=True)
class TenantWindow:
    """One tenant during one closed 1-minute window."""

    tenant_id: str
    cell_id: str
    rps: float  # requests per second seen by the router
    cu: float  # DynamoDB capacity units per second consumed in its cell
    share: float  # fraction of its cell's consumed capacity

    def feature(self, name: str) -> float:
        return float(getattr(self, name))


@dataclass(frozen=True)
class CellHealth:
    """Symptoms of one cell during the same window, as seen by the router."""

    cell_id: str
    requests: float
    errors: float
    rejected: float
    p99_ms: float

    def symptomatic(self, slo_p99_ms: float, max_bad_ratio: float) -> bool:
        if self.requests <= 0:
            return False
        bad_ratio = (self.errors + self.rejected) / self.requests
        return bad_ratio > max_bad_ratio or self.p99_ms > slo_p99_ms


@dataclass
class Baseline:
    """EWMA mean and variance per demand feature, plus the anomaly streak (k consecutive windows)."""

    mean: dict[str, float] = field(default_factory=dict)
    var: dict[str, float] = field(default_factory=dict)
    windows: int = 0
    streak: int = 0


@dataclass(frozen=True)
class Score:
    tenant_id: str
    value: float  # max z over demand features
    feature: str  # the feature that produced it
    ready: bool  # False while the baseline is still warming up


@dataclass(frozen=True)
class Decision:
    tenant_id: str
    action: str  # QUARANTINE | OBSERVE
    from_cell: str
    score: float
    feature: str
    reason: str
