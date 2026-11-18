"""Detector Lambda, triggered every minute by an EventBridge rule (ADR-008: no extra role needed)."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from .loop import ControlLoop

_loop: ControlLoop | None = None
_ssm: Any = None


def _build() -> tuple[ControlLoop, Any]:
    import boto3

    from ..routing import RoutingTable
    from .detector import ZScoreDetector
    from .metrics import CloudWatchMetricsSource
    from .policy import IsolationPolicy
    from .store import DynamoControlStore

    env = os.environ
    ddb = boto3.resource("dynamodb")
    loop = ControlLoop(
        routing=RoutingTable(ddb.Table(env["ROUTING_TABLE_NAME"])),
        metrics=CloudWatchMetricsSource(boto3.client("cloudwatch")),
        detector=ZScoreDetector(alpha=float(env.get("EWMA_ALPHA", "0.1")),
                                warmup_windows=int(env.get("WARMUP_WINDOWS", "5"))),
        policy=IsolationPolicy(threshold=float(env.get("Z_THRESHOLD", "3")), k=int(env.get("K_WINDOWS", "2")),
                               slo_p99_ms=float(env.get("SLO_P99_MS", "500"))),
        store=DynamoControlStore(ddb.Table(env["CONTROL_TABLE_NAME"])),
        quarantine_cell=env.get("QUARANTINE_CELL", "q"),
        lag_seconds=int(env.get("METRICS_LAG_SECONDS", "60")),
    )
    return loop, boto3.client("ssm")


def _mode(ssm: Any) -> str:
    try:
        return ssm.get_parameter(Name="/cellsaas/control/mode")["Parameter"]["Value"].strip()
    except ssm.exceptions.ParameterNotFound:
        return "observe"


def lambda_handler(event: dict, context: Any) -> dict:
    global _loop, _ssm
    if _loop is None:
        _loop, _ssm = _build()
    result = _loop.run(datetime.now(UTC), _mode(_ssm))
    print(json.dumps({"msg": "control-loop", **result}, default=str))
    return result
