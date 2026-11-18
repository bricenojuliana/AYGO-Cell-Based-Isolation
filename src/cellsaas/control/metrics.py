"""Reads one closed 1-minute window of per-tenant and per-cell metrics from CloudWatch (ADR-005)."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from ..routing import Route
from .model import CellHealth, TenantWindow

NAMESPACE = "CellSaaS"
PERIOD = 60


class MetricsSource(Protocol):
    def read(self, start: datetime, end: datetime, routes: Mapping[str, Route]
             ) -> tuple[dict[str, TenantWindow], dict[str, CellHealth]]: ...


class CloudWatchMetricsSource:
    def __init__(self, cloudwatch: Any, namespace: str = NAMESPACE):
        self._cw = cloudwatch
        self._ns = namespace

    def read(self, start: datetime, end: datetime, routes: Mapping[str, Route]):
        queries: list[dict] = []
        keys: dict[str, tuple] = {}

        def add(metric: str, dims: dict[str, str], stat: str, key: tuple) -> None:
            qid = f"m{len(queries)}"
            keys[qid] = key
            queries.append({"Id": qid, "ReturnData": True, "MetricStat": {
                "Metric": {"Namespace": self._ns, "MetricName": metric,
                           "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()]},
                "Period": PERIOD, "Stat": stat}})

        for tenant_id in routes:
            add("Requests", {"TenantId": tenant_id}, "Sum", ("req", tenant_id))
        cells = {r.cell_id for r in routes.values()} | {r.home_cell_id for r in routes.values() if r.home_cell_id}
        for cell_id in sorted(cells):
            for metric, stat in (("Requests", "Sum"), ("Errors5xx", "Sum"), ("Rejected", "Sum"), ("LatencyMs", "p99")):
                add(metric, {"CellId": cell_id}, stat, ("cell", cell_id, metric))
        for metric in ("ConsumedRCU", "ConsumedWCU"):
            for dims in self._dimension_sets(metric):
                if "CellId" in dims and "TenantId" in dims and dims["TenantId"] in routes:
                    add(metric, {"CellId": dims["CellId"], "TenantId": dims["TenantId"]}, "Sum",
                        ("cu", dims["CellId"], dims["TenantId"]))

        values = self._fetch(queries, start, end)
        requests: dict[str, float] = defaultdict(float)
        cell_metrics: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        cu_by_cell_tenant: dict[tuple[str, str], float] = defaultdict(float)
        for qid, value in values.items():
            key = keys[qid]
            if key[0] == "req":
                requests[key[1]] += value
            elif key[0] == "cell":
                cell_metrics[key[1]][key[2]] = value
            else:
                cu_by_cell_tenant[(key[1], key[2])] += value

        cu_by_cell: dict[str, float] = defaultdict(float)
        for (cell_id, _), cu in cu_by_cell_tenant.items():
            cu_by_cell[cell_id] += cu
        windows = {}
        for tenant_id, route in routes.items():
            tenant_cu = sum(cu for (_, t), cu in cu_by_cell_tenant.items() if t == tenant_id)
            in_cell = cu_by_cell_tenant.get((route.cell_id, tenant_id), 0.0)
            cell_total = cu_by_cell.get(route.cell_id, 0.0)
            windows[tenant_id] = TenantWindow(
                tenant_id=tenant_id, cell_id=route.cell_id, rps=requests[tenant_id] / PERIOD, cu=tenant_cu / PERIOD,
                share=(in_cell / cell_total) if cell_total else 0.0)
        health = {c: CellHealth(c, m.get("Requests", 0.0), m.get("Errors5xx", 0.0), m.get("Rejected", 0.0),
                                m.get("LatencyMs", 0.0)) for c, m in cell_metrics.items()}
        return windows, health

    def _dimension_sets(self, metric: str) -> list[dict[str, str]]:
        found, token = [], None
        while True:
            kwargs: dict = {"Namespace": self._ns, "MetricName": metric}
            if token:
                kwargs["NextToken"] = token
            page = self._cw.list_metrics(**kwargs)
            found.extend({d["Name"]: d["Value"] for d in m["Dimensions"]} for m in page.get("Metrics", []))
            token = page.get("NextToken")
            if not token:
                return found

    def _fetch(self, queries: list[dict], start: datetime, end: datetime) -> dict[str, float]:
        values: dict[str, float] = {}
        for i in range(0, len(queries), 500):
            token = None
            while True:
                kwargs: dict = {"MetricDataQueries": queries[i:i + 500], "StartTime": start, "EndTime": end}
                if token:
                    kwargs["NextToken"] = token
                page = self._cw.get_metric_data(**kwargs)
                for result in page.get("MetricDataResults", []):
                    if result.get("Values"):
                        values[result["Id"]] = float(result["Values"][0])
                token = page.get("NextToken")
                if not token:
                    break
        return values
