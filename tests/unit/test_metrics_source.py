from datetime import UTC, datetime

from cellsaas.control.metrics import CloudWatchMetricsSource
from cellsaas.routing import Route


class FakeCloudWatch:
    def __init__(self, data):
        self.data = data  # (metric, frozenset(dims.items()), stat) -> value

    def list_metrics(self, Namespace, MetricName, NextToken=None):
        dims = {d for (m, d, _) in self.data if m == MetricName}
        return {"Metrics": [{"Dimensions": [{"Name": k, "Value": v} for k, v in sorted(d)]} for d in dims]}

    def get_metric_data(self, MetricDataQueries, StartTime, EndTime, NextToken=None):
        results = []
        for q in MetricDataQueries:
            stat = q["MetricStat"]
            dims = frozenset((d["Name"], d["Value"]) for d in stat["Metric"]["Dimensions"])
            value = self.data.get((stat["Metric"]["MetricName"], dims, stat["Stat"]))
            results.append({"Id": q["Id"], "Values": [] if value is None else [value]})
        return {"MetricDataResults": results}


def _d(**dims):
    return frozenset(dims.items())


def test_builds_tenant_windows_and_cell_health():
    data = {
        ("Requests", _d(TenantId="t1"), "Sum"): 600.0,
        ("Requests", _d(TenantId="t2"), "Sum"): 60.0,
        ("Requests", _d(CellId="c1"), "Sum"): 660.0,
        ("Rejected", _d(CellId="c1"), "Sum"): 30.0,
        ("LatencyMs", _d(CellId="c1"), "p99"): 900.0,
        ("ConsumedWCU", _d(CellId="c1", TenantId="t1"), "Sum"): 540.0,
        ("ConsumedWCU", _d(CellId="c1", TenantId="t2"), "Sum"): 60.0,
    }
    routes = {"t1": Route("t1", "c1"), "t2": Route("t2", "c1")}
    windows, cells = CloudWatchMetricsSource(FakeCloudWatch(data)).read(
        datetime(2026, 11, 19, 10, 0, tzinfo=UTC), datetime(2026, 11, 19, 10, 1, tzinfo=UTC), routes)
    assert windows["t1"].rps == 10 and windows["t1"].cu == 9 and windows["t1"].share == 0.9
    assert windows["t2"].rps == 1 and round(windows["t2"].share, 2) == 0.1
    assert cells["c1"].rejected == 30 and cells["c1"].p99_ms == 900
    assert cells["c1"].symptomatic(500, 0.01)
