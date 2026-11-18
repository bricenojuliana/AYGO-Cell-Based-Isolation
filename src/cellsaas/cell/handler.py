"""Cell entry point. Invoked only by the router with lambda:Invoke, never from the internet.

Internal contract (docs/cell-contract.md):
  request  {"op": "CreateOrder"|"GetOrder"|"DailyReport", "tenantId", "requestId", "body"?, "orderId"?, "day"?}
  response {"status": int, "body": {...}}
"""
from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from typing import Any

from ..domain import DomainError
from ..telemetry import MetricsEmitter
from .ports import CapacityUsage, FaultSource, StoreSaturated
from .service import OrderService


class InjectedFault(Exception):
    pass


class CellHandler:
    def __init__(self, cell_id: str, service: OrderService, faults: FaultSource, metrics: MetricsEmitter,
                 rng: Callable[[], float] = random.random, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self._cell_id = cell_id
        self._service = service
        self._faults = faults
        self._metrics = metrics
        self._rng = rng
        self._sleep = sleep
        self._clock = clock

    def handle(self, request: dict) -> dict:
        started = self._clock()
        usage = CapacityUsage()
        tenant_id = str(request.get("tenantId", ""))
        op = str(request.get("op", ""))
        try:
            self._apply_fault()
            response = {"status": 200, "body": self._dispatch(op, tenant_id, request, usage)}
            if op == "CreateOrder":
                response["status"] = 201
        except DomainError as error:
            response = _error(error.status, error.code, error.message)
        except StoreSaturated:
            response = _error(503, "CELL_SATURATED", "The cell is at capacity. Retry later.")
        except InjectedFault:
            response = _error(500, "INJECTED_FAULT", "Injected fault.")
        self._record(tenant_id, op, response["status"], usage, started)
        return response

    def _dispatch(self, op: str, tenant_id: str, request: dict, usage: CapacityUsage) -> dict:
        if op == "CreateOrder":
            return self._service.create(tenant_id, request.get("body"), usage).to_api()
        if op == "GetOrder":
            return self._service.get(tenant_id, request.get("orderId", ""), usage).to_api()
        if op == "DailyReport":
            return self._service.daily_report(tenant_id, request.get("day"), usage).to_api()
        raise _UnknownOperation(op)

    def _apply_fault(self) -> None:
        fault = self._faults.current()
        if fault.delay_ms:
            self._sleep(fault.delay_ms / 1000)
        if fault.error_rate and self._rng() < fault.error_rate:
            raise InjectedFault()

    def _record(self, tenant_id: str, op: str, status: int, usage: CapacityUsage, started: float) -> None:
        self._metrics.emit(
            {"CellId": self._cell_id, "TenantId": tenant_id or "unknown"},
            {
                "CellRequests": (1, "Count"),
                "CellErrors": (1 if status >= 500 else 0, "Count"),
                "CellSaturated": (1 if status == 503 else 0, "Count"),
                "CellLatencyMs": (round((self._clock() - started) * 1000, 2), "Milliseconds"),
                "ConsumedRCU": (usage.read_units, "Count"),
                "ConsumedWCU": (usage.write_units, "Count"),
            },
            dimension_sets=[["CellId"], ["CellId", "TenantId"]],
            properties={"op": op, "status": status},
        )


class _UnknownOperation(DomainError):
    code = "UNKNOWN_OPERATION"

    def __init__(self, op: str):
        super().__init__(f"Unknown operation: {op!r}.")


def _error(status: int, code: str, message: str) -> dict:
    return {"status": status, "body": {"code": code, "message": message}}


_handler: CellHandler | None = None


def _build() -> CellHandler:
    import boto3
    from botocore.config import Config

    from .faults import SsmFaultSource
    from .repository import DynamoOrderRepository

    cell_id = os.environ["CELL_ID"]
    # Fail fast on saturation instead of retrying for seconds: saturation is what we want to observe.
    config = Config(retries={"max_attempts": 2, "mode": "standard"}, connect_timeout=2, read_timeout=3)
    table = boto3.resource("dynamodb", config=config).Table(os.environ["ORDERS_TABLE_NAME"])
    return CellHandler(
        cell_id=cell_id,
        service=OrderService(DynamoOrderRepository(table)),
        faults=SsmFaultSource(boto3.client("ssm", config=config), f"/cellsaas/faults/{cell_id}"),
        metrics=MetricsEmitter(os.environ.get("METRICS_NAMESPACE", "CellSaaS")),
    )


def lambda_handler(event: dict, context: Any) -> dict:
    global _handler
    if _handler is None:
        _handler = _build()
    return _handler.handle(event)
