"""Real adapters against moto's DynamoDB (no AWS credentials needed)."""
import boto3
import pytest
from moto import mock_aws

from cellsaas.cell.ports import CapacityUsage
from cellsaas.cell.repository import DynamoOrderRepository
from cellsaas.domain import Order, OrderItem
from cellsaas.routing import QUARANTINED, RoutingTable


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(var, "testing")
    with mock_aws():
        yield boto3.resource("dynamodb")


def _orders_table(ddb):
    return ddb.create_table(
        TableName="orders", BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
    )


def _routing_table(ddb):
    return ddb.create_table(
        TableName="routing", BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
    )


def _order(tenant, order_id, day="2026-11-19"):
    return Order(tenant, order_id, (OrderItem("TINTO", 2, 100),), f"{day}T10:00:00Z")


def test_repository_round_trip_and_tenant_scoping(aws):
    repo = DynamoOrderRepository(_orders_table(aws))
    usage = CapacityUsage()
    repo.put(_order("cafe-01", "CC-AAAA-0001"), usage)
    assert repo.get("cafe-01", "CC-AAAA-0001", usage) == _order("cafe-01", "CC-AAAA-0001")
    assert repo.get("cafe-02", "CC-AAAA-0001", usage) is None


def test_repository_daily_report_reads_only_that_day_and_tenant(aws):
    repo = DynamoOrderRepository(_orders_table(aws))
    usage = CapacityUsage()
    repo.put(_order("cafe-01", "CC-AAAA-0001"), usage)
    repo.put(_order("cafe-01", "CC-AAAA-0002", day="2026-11-18"), usage)
    repo.put(_order("cafe-02", "CC-AAAA-0003"), usage)
    assert [o.order_id for o in repo.list_day("cafe-01", "2026-11-19", usage)] == ["CC-AAAA-0001"]


def test_routing_register_quarantine_release(aws):
    routing = RoutingTable(_routing_table(aws))
    routing.register("cafe-01", "hash1", "c1")
    assert routing.tenant_for_key_hash("hash1") == "cafe-01"
    assert routing.route("cafe-01").cell_id == "c1"

    assert routing.quarantine("cafe-01", "q") is True
    route = routing.route("cafe-01")
    assert (route.cell_id, route.status, route.home_cell_id) == ("q", QUARANTINED, "c1")
    assert routing.quarantine("cafe-01", "q") is False  # idempotent

    assert routing.release("cafe-01") is True
    route = routing.route("cafe-01")
    assert (route.cell_id, route.status, route.home_cell_id) == ("c1", "ACTIVE", None)
    assert routing.release("cafe-01") is False


def test_routing_lists_and_reassigns_routes(aws):
    routing = RoutingTable(_routing_table(aws))
    for i in range(3):
        routing.register(f"cafe-0{i}", f"h{i}", "c1")
    routing.assign("cafe-00", "pool")
    assert sorted((r.tenant_id, r.cell_id) for r in routing.routes()) == [
        ("cafe-00", "pool"), ("cafe-01", "c1"), ("cafe-02", "c1")]
