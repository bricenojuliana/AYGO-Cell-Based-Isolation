"""DynamoDB adapter. Key: pk = TENANT#<tenantId>, sk = ORDER#<orderId> (SPEC 5.2, RF05).

Every access is scoped to one tenant partition, so a tenant can never read another tenant's items.
Reading one order is a GetItem. The daily report queries the whole tenant partition and filters by
day, so its cost grows with the tenant's history: it is the expensive operation of RF02 on purpose.
"""
from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from ..domain import Order, OrderItem
from .ports import CapacityUsage, StoreSaturated

_SATURATION_CODES = {"ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded"}


def _pk(tenant_id: str) -> str:
    return f"TENANT#{tenant_id}"


class DynamoOrderRepository:
    def __init__(self, table: Any):
        """`table` is a boto3 DynamoDB Table resource."""
        self._table = table

    def put(self, order: Order, usage: CapacityUsage) -> None:
        item = {
            "pk": _pk(order.tenant_id),
            "sk": f"ORDER#{order.order_id}",
            "day": order.day,
            "orderId": order.order_id,
            "createdAt": order.created_at,
            "items": [{"sku": i.sku, "quantity": i.quantity, "unitPriceCents": i.unit_price_cents} for i in order.items],
        }
        response = self._call(self._table.put_item, Item=item, ReturnConsumedCapacity="TOTAL")
        usage.write_units += _units(response)

    def get(self, tenant_id: str, order_id: str, usage: CapacityUsage) -> Order | None:
        response = self._call(self._table.get_item, Key={"pk": _pk(tenant_id), "sk": f"ORDER#{order_id}"},
                              ReturnConsumedCapacity="TOTAL")
        usage.read_units += _units(response)
        item = response.get("Item")
        return _to_order(tenant_id, item) if item else None

    def list_day(self, tenant_id: str, day: str, usage: CapacityUsage) -> list[Order]:
        orders, start = [], None
        while True:
            kwargs = {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "FilterExpression": "#day = :day",
                "ExpressionAttributeNames": {"#day": "day"},
                "ExpressionAttributeValues": {":pk": _pk(tenant_id), ":prefix": "ORDER#", ":day": day},
                "ReturnConsumedCapacity": "TOTAL",
            }
            if start:
                kwargs["ExclusiveStartKey"] = start
            response = self._call(self._table.query, **kwargs)
            usage.read_units += _units(response)
            orders.extend(_to_order(tenant_id, item) for item in response.get("Items", []))
            start = response.get("LastEvaluatedKey")
            if not start:
                return orders

    @staticmethod
    def _call(method, **kwargs):
        try:
            return method(**kwargs)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in _SATURATION_CODES:
                raise StoreSaturated() from error
            raise


def _units(response: dict) -> float:
    return float((response.get("ConsumedCapacity") or {}).get("CapacityUnits", 0.0))


def _to_order(tenant_id: str, item: dict) -> Order:
    return Order(
        tenant_id=tenant_id,
        order_id=item["orderId"],
        created_at=item["createdAt"],
        items=tuple(OrderItem(sku=i["sku"], quantity=int(i["quantity"]), unit_price_cents=int(i["unitPriceCents"]))
                    for i in item["items"]),
    )
