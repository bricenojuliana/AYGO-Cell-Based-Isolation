"""What each tenant sends, and when (pure logic, unit-tested)."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class NoisyPhase:
    """Between `start_s` and `end_s` (seconds from run start) `tenant_id` sends `multiplier` times its rate."""

    tenant_id: str
    start_s: float
    end_s: float
    multiplier: float = 10.0

    def factor(self, tenant_id: str, elapsed_s: float) -> float:
        return self.multiplier if tenant_id == self.tenant_id and self.start_s <= elapsed_s < self.end_s else 1.0


@dataclass(frozen=True)
class LoadProfile:
    rate_rps: float = 2.0  # per tenant, nominal
    create_ratio: float = 0.8  # the rest are reads of the tenant's own orders
    report_ratio: float = 0.05  # daily report (expensive) share of all requests
    noisy: NoisyPhase | None = None

    def rate(self, tenant_id: str, elapsed_s: float) -> float:
        return self.rate_rps * (self.noisy.factor(tenant_id, elapsed_s) if self.noisy else 1.0)

    def next_gap(self, tenant_id: str, elapsed_s: float, rng: random.Random) -> float:
        """Poisson arrivals: exponential inter-arrival time at the current rate (open loop)."""
        return rng.expovariate(self.rate(tenant_id, elapsed_s))

    def pick_op(self, rng: random.Random, has_orders: bool) -> str:
        r = rng.random()
        if r < self.report_ratio:
            return "DailyReport"
        if r < self.report_ratio + self.create_ratio or not has_orders:
            return "CreateOrder"
        return "GetOrder"
