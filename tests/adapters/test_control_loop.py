"""Control loop end to end with the real DynamoDB adapters on moto and a scripted metrics source."""
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from cellsaas.control.detector import ZScoreDetector
from cellsaas.control.loop import ControlLoop
from cellsaas.control.model import CellHealth, TenantWindow
from cellsaas.control.policy import IsolationPolicy
from cellsaas.control.store import DynamoControlStore
from cellsaas.routing import QUARANTINED, RoutingTable


class ScriptedMetrics:
    def __init__(self):
        self.noisy = False

    def read(self, start, end, routes):
        windows = {}
        for t, r in routes.items():
            rps = 50.0 if (self.noisy and t == "cafe-01") else 5.0 + (hash((t, start.minute)) % 3) * 0.1
            windows[t] = TenantWindow(t, r.cell_id, rps, rps, 0.1)
        cells = {"c1": CellHealth("c1", 3000, 0, 300 if self.noisy else 0, 900 if self.noisy else 80)}
        return windows, cells


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        ddb = boto3.resource("dynamodb")
        routing = ddb.create_table(TableName="routing", BillingMode="PAY_PER_REQUEST",
                                   AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
                                   KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}])
        control = ddb.create_table(TableName="control", BillingMode="PAY_PER_REQUEST",
                                   AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                                         {"AttributeName": "sk", "AttributeType": "S"}],
                                   KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                                              {"AttributeName": "sk", "KeyType": "RANGE"}])
        table = RoutingTable(routing)
        for i in range(1, 4):
            table.register(f"cafe-0{i}", f"h{i}", "c1")
        yield table, control


def _loop(routing, control, metrics):
    return ControlLoop(routing, metrics, ZScoreDetector(warmup_windows=5), IsolationPolicy(k=2),
                       DynamoControlStore(control), quarantine_cell="q")


def test_rf08_rf09_rf10_noisy_tenant_is_detected_isolated_and_audited(env):
    routing, control = env
    metrics = ScriptedMetrics()
    loop = _loop(routing, control, metrics)
    t0 = datetime(2026, 11, 19, 10, 0, 30, tzinfo=UTC)
    for minute in range(8):  # warm-up with normal traffic
        assert loop.run(t0 + timedelta(minutes=minute), "act")["decisions"] == []
    metrics.noisy = True
    first = loop.run(t0 + timedelta(minutes=8), "act")
    assert first["decisions"] == []  # k = 2: one anomalous window is not enough
    second = loop.run(t0 + timedelta(minutes=9), "act")
    assert [d["tenant_id"] for d in second["decisions"]] == ["cafe-01"]

    route = routing.route("cafe-01")
    assert (route.cell_id, route.status, route.home_cell_id) == ("q", QUARANTINED, "c1")
    audit = control.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "AUDIT"})["Items"]
    assert len(audit) == 1 and audit[0]["applied"] is True and audit[0]["feature"] == "rps"
    features = control.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "FEATURES"})["Items"]
    assert len(features) == 10

    # The anomalous windows must not poison the noisy tenant's baseline.
    baseline = DynamoControlStore(control).load_baselines()["cafe-01"]
    assert baseline.mean["rps"] < 6


def test_observe_mode_audits_without_isolating(env):
    routing, control = env
    metrics = ScriptedMetrics()
    loop = _loop(routing, control, metrics)
    t0 = datetime(2026, 11, 19, 10, 0, 30, tzinfo=UTC)
    for minute in range(8):
        loop.run(t0 + timedelta(minutes=minute), "observe")
    metrics.noisy = True
    loop.run(t0 + timedelta(minutes=8), "observe")
    result = loop.run(t0 + timedelta(minutes=9), "observe")
    assert result["decisions"][0]["action"] == "OBSERVE"
    assert routing.route("cafe-01").cell_id == "c1"


def test_off_mode_does_nothing(env):
    routing, control = env
    assert _loop(routing, control, ScriptedMetrics()).run(datetime(2026, 11, 19, tzinfo=UTC), "off") == {"mode": "off"}
