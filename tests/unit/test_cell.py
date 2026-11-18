from datetime import UTC, datetime

import pytest

from cellsaas.cell.handler import CellHandler
from cellsaas.cell.ports import CapacityUsage, Fault
from cellsaas.cell.service import OrderService
from cellsaas.domain import OrderNotFound
from tests.fakes import CapturingMetrics, FakeOrderRepository, FixedFaults

NOW = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
BODY = {"items": [{"sku": "TINTO", "quantity": 2, "unitPriceCents": 250_000}]}


def _service(repo=None):
    ids = iter([f"CC-AAAA-000{i}" for i in range(1, 10)])
    return OrderService(repo or FakeOrderRepository(), now=lambda: NOW, id_factory=lambda: next(ids))


def _handler(repo=None, fault=None, rng=0.0):
    metrics = CapturingMetrics()
    handler = CellHandler("c1", _service(repo), FixedFaults(fault), metrics, rng=lambda: rng, sleep=lambda s: None)
    return handler, metrics


def test_service_create_get_and_report():
    service = _service()
    usage = CapacityUsage()
    order = service.create("cafe-01", BODY, usage)
    assert service.get("cafe-01", order.order_id, usage) == order
    report = service.daily_report("cafe-01", None, usage)
    assert (report.day, report.orders, report.total_cents) == ("2026-11-19", 1, 500_000)


def test_qas05_a_tenant_cannot_read_another_tenants_order():
    service = _service()
    order = service.create("cafe-01", BODY, CapacityUsage())
    with pytest.raises(OrderNotFound):
        service.get("cafe-02", order.order_id, CapacityUsage())
    assert service.daily_report("cafe-02", "2026-11-19", CapacityUsage()).orders == 0


def test_handler_creates_order_and_emits_tenant_metrics():
    handler, metrics = _handler()
    response = handler.handle({"op": "CreateOrder", "tenantId": "cafe-01", "body": BODY})
    assert response["status"] == 201
    assert response["body"]["totalCents"] == 500_000
    record = metrics.records[-1]
    assert record["TenantId"] == "cafe-01" and record["CellId"] == "c1"
    assert record["ConsumedWCU"] == 1 and record["CellErrors"] == 0
    assert ["CellId", "TenantId"] in record["_aws"]["CloudWatchMetrics"][0]["Dimensions"]


def test_handler_maps_domain_errors():
    handler, _ = _handler()
    assert handler.handle({"op": "GetOrder", "tenantId": "cafe-01", "orderId": "CC-AAAA-9999"})["status"] == 404
    assert handler.handle({"op": "CreateOrder", "tenantId": "cafe-01", "body": {}})["status"] == 400
    assert handler.handle({"op": "Nope", "tenantId": "cafe-01"})["body"]["code"] == "UNKNOWN_OPERATION"


def test_handler_reports_saturation_as_503():
    handler, metrics = _handler(repo=FakeOrderRepository(saturated=True))
    response = handler.handle({"op": "CreateOrder", "tenantId": "cafe-01", "body": BODY})
    assert response["status"] == 503 and response["body"]["code"] == "CELL_SATURATED"
    assert metrics.records[-1]["CellSaturated"] == 1


def test_rf12_injected_fault_fails_requests():
    handler, metrics = _handler(fault=Fault(error_rate=1.0), rng=0.5)
    assert handler.handle({"op": "CreateOrder", "tenantId": "cafe-01", "body": BODY})["status"] == 500
    assert metrics.records[-1]["CellErrors"] == 1


def test_rf12_partial_fault_respects_rate():
    handler, _ = _handler(fault=Fault(error_rate=0.3), rng=0.5)
    assert handler.handle({"op": "CreateOrder", "tenantId": "cafe-01", "body": BODY})["status"] == 201
