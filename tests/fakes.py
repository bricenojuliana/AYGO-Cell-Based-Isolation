"""In-memory doubles for the ports, so use cases are tested without AWS (QAS09)."""
from __future__ import annotations

import io
import json

from cellsaas.cell.ports import CapacityUsage, Fault, StoreSaturated
from cellsaas.domain import Order
from cellsaas.routing import ACTIVE, QUARANTINED, Route
from cellsaas.telemetry import MetricsEmitter


class FakeOrderRepository:
    def __init__(self, saturated: bool = False):
        self.orders: dict[tuple[str, str], Order] = {}
        self.saturated = saturated

    def put(self, order: Order, usage: CapacityUsage) -> None:
        self._check()
        self.orders[(order.tenant_id, order.order_id)] = order
        usage.write_units += 1

    def get(self, tenant_id: str, order_id: str, usage: CapacityUsage) -> Order | None:
        self._check()
        usage.read_units += 0.5
        return self.orders.get((tenant_id, order_id))

    def list_day(self, tenant_id: str, day: str, usage: CapacityUsage) -> list[Order]:
        self._check()
        found = [o for (t, _), o in self.orders.items() if t == tenant_id and o.day == day]
        usage.read_units += len(found)
        return found

    def _check(self) -> None:
        if self.saturated:
            raise StoreSaturated()


class FixedFaults:
    def __init__(self, fault: Fault | None = None):
        self.fault = fault or Fault()

    def current(self) -> Fault:
        return self.fault


class CapturingMetrics(MetricsEmitter):
    def __init__(self):
        self.buffer = io.StringIO()
        super().__init__("Test", stream=self.buffer, clock=lambda: 1_700_000_000.0)

    @property
    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.buffer.getvalue().splitlines()]


class FakeRouting:
    """Stands in for RoutingTable in router tests."""

    def __init__(self, keys: dict[str, str] | None = None, routes: dict[str, Route] | None = None):
        self.keys = keys or {}
        self.routes_by_tenant = routes or {}
        self.route_reads = 0

    def tenant_for_key_hash(self, key_hash: str) -> str | None:
        return self.keys.get(key_hash)

    def route(self, tenant_id: str) -> Route | None:
        self.route_reads += 1
        return self.routes_by_tenant.get(tenant_id)


class FakeInvoker:
    """Records calls and answers with per-cell scripted responses or a callable."""

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    def invoke(self, cell_id: str, request: dict) -> dict:
        self.calls.append((cell_id, request))
        answer = self.responses[cell_id]
        if isinstance(answer, Exception):
            raise answer
        return answer(request) if callable(answer) else answer


__all__ = ["ACTIVE", "QUARANTINED"]
