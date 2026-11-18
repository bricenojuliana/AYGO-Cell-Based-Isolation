import json

from cellsaas.router.directory import CellDirectory, TenantAuthenticator
from cellsaas.router.handler import RouterHandler
from cellsaas.router.invoker import CellUnavailable
from cellsaas.routing import ACTIVE, QUARANTINED, Route, hash_api_key
from tests.fakes import CapturingMetrics, FakeInvoker, FakeRouting

PEPPER = "test-pepper"
KEY = "key-cafe-01"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _event(route_key="POST /orders", key=KEY, body=None, path=None, query=None):
    return {
        "routeKey": route_key,
        "headers": {"x-api-key": key} if key else {},
        "body": json.dumps(body if body is not None else {"items": []}),
        "pathParameters": path,
        "queryStringParameters": query,
        "requestContext": {"requestId": "req-1"},
    }


def _router(route, responses, clock=None):
    clock = clock or Clock()
    routing = FakeRouting(keys={hash_api_key(KEY, PEPPER): "cafe-01"}, routes={"cafe-01": route})
    invoker = FakeInvoker(responses)
    metrics = CapturingMetrics()
    router = RouterHandler(TenantAuthenticator(routing, PEPPER, clock=clock), CellDirectory(routing, 10, clock),
                           invoker, metrics, clock=clock)
    return router, invoker, metrics, routing


def test_rf03_rejects_missing_or_unknown_key():
    router, invoker, _, _ = _router(Route("cafe-01", "c1"), {})
    assert router.handle(_event(key=None))["statusCode"] == 401
    assert router.handle(_event(key="stolen"))["statusCode"] == 401
    assert invoker.calls == []


def test_rf04_routes_to_the_tenants_cell_with_identity_from_key():
    router, invoker, metrics, _ = _router(Route("cafe-01", "c2"), {"c2": {"status": 201, "body": {"orderId": "x"}}})
    response = router.handle(_event())
    assert response["statusCode"] == 201
    assert response["headers"]["x-cell-id"] == "c2"
    cell, request = invoker.calls[0]
    assert cell == "c2" and request["tenantId"] == "cafe-01" and request["op"] == "CreateOrder"
    assert metrics.records[-1]["TenantId"] == "cafe-01" and metrics.records[-1]["Requests"] == 1


def test_route_cache_avoids_table_reads_until_ttl():
    clock = Clock()
    router, _, _, routing = _router(Route("cafe-01", "c1"), {"c1": {"status": 201, "body": {}}}, clock)
    router.handle(_event())
    router.handle(_event())
    assert routing.route_reads == 1
    clock.now = 11
    router.handle(_event())
    assert routing.route_reads == 2


def test_invalid_json_is_400_without_calling_a_cell():
    router, invoker, _, _ = _router(Route("cafe-01", "c1"), {})
    event = _event()
    event["body"] = "{oops"
    assert router.handle(event)["statusCode"] == 400
    assert invoker.calls == []


def test_unknown_route_is_404():
    router, _, _, _ = _router(Route("cafe-01", "c1"), {})
    assert router.handle(_event(route_key="DELETE /orders"))["statusCode"] == 404


def test_cell_throttling_becomes_429_and_counts_as_rejected():
    router, _, metrics, _ = _router(Route("cafe-01", "c1"), {"c1": CellUnavailable(429, "CELL_THROTTLED")})
    response = router.handle(_event())
    assert response["statusCode"] == 429
    assert json.loads(response["body"])["requestId"] == "req-1"
    assert metrics.records[-1]["Rejected"] == 1


def test_rf09_quarantined_tenant_goes_to_quarantine_cell():
    route = Route("cafe-01", "q", QUARANTINED, "c1")
    router, invoker, _, _ = _router(route, {"q": {"status": 201, "body": {}}})
    router.handle(_event())
    assert invoker.calls[0][0] == "q"


def test_adr007_read_fallback_to_home_cell_for_old_orders():
    route = Route("cafe-01", "q", QUARANTINED, "c1")
    responses = {"q": {"status": 404, "body": {"code": "ORDER_NOT_FOUND"}}, "c1": {"status": 200, "body": {"orderId": "o"}}}
    router, invoker, _, _ = _router(route, responses)
    response = router.handle(_event("GET /orders/{orderId}", path={"orderId": "CC-AAAA-0001"}))
    assert response["statusCode"] == 200 and response["headers"]["x-cell-id"] == "c1"
    assert [c for c, _ in invoker.calls] == ["q", "c1"]


def test_no_fallback_for_active_tenants():
    responses = {"c1": {"status": 404, "body": {"code": "ORDER_NOT_FOUND"}}}
    router, invoker, _, _ = _router(Route("cafe-01", "c1", ACTIVE), responses)
    assert router.handle(_event("GET /orders/{orderId}", path={"orderId": "CC-AAAA-0001"}))["statusCode"] == 404
    assert len(invoker.calls) == 1
