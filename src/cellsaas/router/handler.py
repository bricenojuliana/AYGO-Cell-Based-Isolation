"""Router entry point behind API Gateway HTTP API (payload format 2.0). SPEC 5.3."""
from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable
from typing import Any

from ..telemetry import MetricsEmitter
from .directory import CellDirectory, TenantAuthenticator
from .invoker import CellInvoker, CellUnavailable

ROUTES = {
    "POST /orders": "CreateOrder",
    "GET /orders/{orderId}": "GetOrder",
    "GET /reports/daily": "DailyReport",
}


class RouterHandler:
    def __init__(self, authenticator: TenantAuthenticator, directory: CellDirectory, invoker: CellInvoker,
                 metrics: MetricsEmitter, clock: Callable[[], float] = time.monotonic):
        self._auth = authenticator
        self._directory = directory
        self._invoker = invoker
        self._metrics = metrics
        self._clock = clock

    def handle(self, event: dict) -> dict:
        started = self._clock()
        request_id = (event.get("requestContext") or {}).get("requestId", "")
        op = ROUTES.get(event.get("routeKey", ""))
        tenant_id = self._auth.authenticate((event.get("headers") or {}).get("x-api-key"))
        if tenant_id is None:
            return _http(401, {"code": "UNAUTHORIZED", "message": "Missing or invalid API key.", "requestId": request_id})
        if op is None:
            return _http(404, {"code": "NOT_FOUND", "message": "Unknown route.", "requestId": request_id})
        route = self._directory.resolve(tenant_id)
        if route is None:
            return _http(403, {"code": "TENANT_NOT_PLACED", "message": "Tenant has no cell.", "requestId": request_id})

        body, parse_error = _parse_body(event) if op == "CreateOrder" else (None, None)
        if parse_error:
            return _http(400, {"code": "INVALID_REQUEST", "message": parse_error, "requestId": request_id})
        cell_request = {
            "op": op, "tenantId": tenant_id, "requestId": request_id, "body": body,
            "orderId": (event.get("pathParameters") or {}).get("orderId"),
            "day": (event.get("queryStringParameters") or {}).get("day"),
        }
        cell_id, status, payload = self._call(route.cell_id, cell_request)
        # Read fallback: a quarantined tenant's history stays in its home cell (ADR-007).
        if route.quarantined and op == "GetOrder" and status == 404 and route.home_cell_id:
            cell_id, status, payload = self._call(route.home_cell_id, cell_request)
        payload = {**payload, "requestId": request_id} if status >= 400 else payload
        self._record(tenant_id, cell_id, op, status, started)
        return _http(status, payload, {"x-cell-id": cell_id})

    def _call(self, cell_id: str, request: dict) -> tuple[str, int, dict]:
        try:
            response = self._invoker.invoke(cell_id, request)
            return cell_id, int(response["status"]), response["body"]
        except CellUnavailable as error:
            return cell_id, error.status, {"code": error.code, "message": "The cell could not serve the request."}

    def _record(self, tenant_id: str, cell_id: str, op: str, status: int, started: float) -> None:
        self._metrics.emit(
            {"TenantId": tenant_id, "CellId": cell_id},
            {
                "Requests": (1, "Count"),
                "Errors5xx": (1 if status >= 500 else 0, "Count"),
                "Rejected": (1 if status in (429, 503) else 0, "Count"),
                "LatencyMs": (round((self._clock() - started) * 1000, 2), "Milliseconds"),
            },
            dimension_sets=[["TenantId"], ["CellId"]],
            properties={"op": op, "status": status},
        )


def _parse_body(event: dict) -> tuple[Any, str | None]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        return json.loads(raw), None
    except ValueError:
        return None, "The body must be valid JSON."


def _http(status: int, body: dict, headers: dict | None = None) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json", **(headers or {})},
            "body": json.dumps(body)}


_handler: RouterHandler | None = None


def _build() -> RouterHandler:
    import boto3
    from botocore.config import Config

    from ..routing import RoutingTable

    config = Config(retries={"max_attempts": 1, "mode": "standard"}, connect_timeout=2, read_timeout=10)
    routing = RoutingTable(boto3.resource("dynamodb").Table(os.environ["ROUTING_TABLE_NAME"]))
    return RouterHandler(
        authenticator=TenantAuthenticator(routing, os.environ["API_KEY_PEPPER"]),
        directory=CellDirectory(routing, float(os.environ.get("ROUTE_CACHE_SECONDS", "10"))),
        invoker=CellInvoker(boto3.client("lambda", config=config), os.environ.get("CELL_FUNCTION_PREFIX", "cellsaas-cell-")),
        metrics=MetricsEmitter(os.environ.get("METRICS_NAMESPACE", "CellSaaS")),
    )


def lambda_handler(event: dict, context: Any) -> dict:
    global _handler
    if _handler is None:
        _handler = _build()
    return _handler.handle(event)
