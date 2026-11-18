"""Control-plane state in DynamoDB: baselines, audit log and per-window features (SPEC RF10).

Table cellsaas-control, key (pk, sk):
  BASELINE / <tenantId>          EWMA baseline and streak
  AUDIT    / <iso time>#<tenant> every decision: window, score, threshold, action, outcome (append-only)
  FEATURES / <window start iso>  all tenants' features and scores for that window (offline evaluation)
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from .model import Baseline


def _dec(value: Any) -> Any:
    return json.loads(json.dumps(value), parse_float=Decimal)


class DynamoControlStore:
    def __init__(self, table: Any):
        self._table = table

    def load_baselines(self) -> dict[str, Baseline]:
        baselines, start = {}, None
        while True:
            kwargs: dict = {"KeyConditionExpression": "pk = :pk", "ExpressionAttributeValues": {":pk": "BASELINE"}}
            if start:
                kwargs["ExclusiveStartKey"] = start
            page = self._table.query(**kwargs)
            for item in page.get("Items", []):
                baselines[item["sk"]] = Baseline(
                    mean={k: float(v) for k, v in item.get("mean", {}).items()},
                    var={k: float(v) for k, v in item.get("var", {}).items()},
                    windows=int(item.get("windows", 0)), streak=int(item.get("streak", 0)))
            start = page.get("LastEvaluatedKey")
            if not start:
                return baselines

    def save_baselines(self, baselines: dict[str, Baseline]) -> None:
        with self._table.batch_writer() as batch:
            for tenant_id, b in baselines.items():
                batch.put_item(Item=_dec({"pk": "BASELINE", "sk": tenant_id, "mean": b.mean, "var": b.var,
                                          "windows": b.windows, "streak": b.streak}))

    def append_audit(self, at_iso: str, record: dict) -> None:
        self._table.put_item(Item=_dec({"pk": "AUDIT", "sk": f"{at_iso}#{record['tenantId']}", **record}))

    def save_features(self, window_iso: str, record: dict) -> None:
        self._table.put_item(Item=_dec({"pk": "FEATURES", "sk": window_iso, **record}))
