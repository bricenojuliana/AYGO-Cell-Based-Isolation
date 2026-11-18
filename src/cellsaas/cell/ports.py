"""Interfaces the cell's use cases depend on; adapters implement them, tests fake them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import Order


class StoreSaturated(Exception):
    """The cell's table rejected the request for lack of capacity (provisioned throughput exceeded)."""


@dataclass
class CapacityUsage:
    """DynamoDB capacity units consumed while handling one request (a demand feature for the detector)."""

    read_units: float = 0.0
    write_units: float = 0.0


class OrderRepository(Protocol):
    def put(self, order: Order, usage: CapacityUsage) -> None: ...

    def get(self, tenant_id: str, order_id: str, usage: CapacityUsage) -> Order | None: ...

    def list_day(self, tenant_id: str, day: str, usage: CapacityUsage) -> list[Order]: ...


@dataclass(frozen=True)
class Fault:
    """Injected fault for this cell (SPEC RF12). error_rate in [0, 1]; delay_ms added before work."""

    error_rate: float = 0.0
    delay_ms: int = 0


class FaultSource(Protocol):
    def current(self) -> Fault: ...
