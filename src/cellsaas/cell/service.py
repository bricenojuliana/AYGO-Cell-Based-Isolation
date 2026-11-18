"""Use cases of a cell. Depends only on ports (hexagonal layering reused from Campus Café)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..domain import (
    DailyReport,
    Order,
    OrderNotFound,
    build_report,
    new_order_id,
    parse_items,
    validate_day,
    validate_order_id,
    validate_tenant_id,
)
from .ports import CapacityUsage, OrderRepository


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OrderService:
    def __init__(self, repository: OrderRepository, now: Callable[[], datetime] = _utc_now,
                 id_factory: Callable[[], str] = new_order_id):
        self._repository = repository
        self._now = now
        self._new_id = id_factory

    def create(self, tenant_id: str, body: Any, usage: CapacityUsage) -> Order:
        order = Order(
            tenant_id=validate_tenant_id(tenant_id),
            order_id=self._new_id(),
            items=parse_items(body),
            created_at=self._now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._repository.put(order, usage)
        return order

    def get(self, tenant_id: str, order_id: str, usage: CapacityUsage) -> Order:
        order = self._repository.get(validate_tenant_id(tenant_id), validate_order_id(order_id), usage)
        if order is None:
            raise OrderNotFound()
        return order

    def daily_report(self, tenant_id: str, day: str | None, usage: CapacityUsage) -> DailyReport:
        day = validate_day(day) if day is not None else self._now().strftime("%Y-%m-%d")
        return build_report(day, self._repository.list_day(validate_tenant_id(tenant_id), day, usage))
