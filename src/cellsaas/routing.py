"""Routing table shared by the router (reads) and the control plane (writes). SPEC RF03, RF04, RF06, RF09.

Single DynamoDB table, two item kinds:
  pk = TENANT#<tenantId>  -> cellId, status (ACTIVE | QUARANTINED), homeCellId (cell before quarantine)
  pk = KEY#<hmac(apiKey)> -> tenantId   (API keys are never stored in clear)
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

ACTIVE = "ACTIVE"
QUARANTINED = "QUARANTINED"


def hash_api_key(api_key: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), api_key.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Route:
    tenant_id: str
    cell_id: str
    status: str = ACTIVE
    home_cell_id: str | None = None

    @property
    def quarantined(self) -> bool:
        return self.status == QUARANTINED


class RoutingTable:
    def __init__(self, table: Any):
        """`table` is a boto3 DynamoDB Table resource."""
        self._table = table

    # ---- reads (router) ----
    def tenant_for_key_hash(self, key_hash: str) -> str | None:
        item = self._table.get_item(Key={"pk": f"KEY#{key_hash}"}).get("Item")
        return item["tenantId"] if item else None

    def route(self, tenant_id: str) -> Route | None:
        item = self._table.get_item(Key={"pk": f"TENANT#{tenant_id}"}, ConsistentRead=True).get("Item")
        return _to_route(item) if item else None

    def routes(self) -> list[Route]:
        routes, start = [], None
        while True:
            kwargs: dict = {"FilterExpression": "begins_with(pk, :p)", "ExpressionAttributeValues": {":p": "TENANT#"}}
            if start:
                kwargs["ExclusiveStartKey"] = start
            page = self._table.scan(**kwargs)
            routes.extend(_to_route(item) for item in page.get("Items", []))
            start = page.get("LastEvaluatedKey")
            if not start:
                return routes

    # ---- writes (control plane and scripts) ----
    def register(self, tenant_id: str, key_hash: str, cell_id: str) -> None:
        self._table.put_item(Item={"pk": f"KEY#{key_hash}", "tenantId": tenant_id})
        self._table.put_item(Item={"pk": f"TENANT#{tenant_id}", "tenantId": tenant_id,
                                   "cellId": cell_id, "status": ACTIVE})

    def assign(self, tenant_id: str, cell_id: str) -> None:
        """Places an active tenant in a cell (used to switch topology between pool and cells)."""
        self._table.put_item(Item={"pk": f"TENANT#{tenant_id}", "tenantId": tenant_id,
                                   "cellId": cell_id, "status": ACTIVE})

    def quarantine(self, tenant_id: str, quarantine_cell_id: str) -> bool:
        """Moves the tenant to the quarantine cell, remembering its home cell. Idempotent:
        returns False (and changes nothing) if the tenant is already quarantined."""
        try:
            self._table.update_item(
                Key={"pk": f"TENANT#{tenant_id}"},
                UpdateExpression="SET homeCellId = cellId, cellId = :q, #s = :quarantined",
                ConditionExpression="attribute_exists(pk) AND #s = :active",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":q": quarantine_cell_id, ":quarantined": QUARANTINED, ":active": ACTIVE},
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def release(self, tenant_id: str) -> bool:
        """Returns a quarantined tenant to its home cell (manual, SPEC RF11). Idempotent."""
        try:
            self._table.update_item(
                Key={"pk": f"TENANT#{tenant_id}"},
                UpdateExpression="SET cellId = homeCellId, #s = :active REMOVE homeCellId",
                ConditionExpression="#s = :quarantined",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":quarantined": QUARANTINED, ":active": ACTIVE},
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False


def _to_route(item: dict) -> Route:
    return Route(tenant_id=item["tenantId"], cell_id=item["cellId"], status=item.get("status", ACTIVE),
                 home_cell_id=item.get("homeCellId"))
