"""The load generator against a local fake API: open loop, CSV schema, order reads after creates."""
import asyncio
import csv

from aiohttp import web

from experiments.cellexp.loadgen import LoadGenerator
from experiments.cellexp.profile import LoadProfile


async def _serve():
    created = []

    async def create(request):
        created.append(1)
        await asyncio.sleep(0.01)
        return web.json_response({"orderId": f"CC-AAAA-{len(created):04d}"}, status=201, headers={"x-cell-id": "c1"})

    async def get(request):
        return web.json_response({}, headers={"x-cell-id": "c1"})

    app = web.Application()
    app.add_routes([web.post("/orders", create), web.get("/orders/{id}", get), web.get("/reports/daily", get)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def test_generates_open_loop_traffic_and_writes_one_row_per_request(tmp_path):
    async def scenario():
        runner, url = await _serve()
        tenants = [{"tenantId": f"cafe-0{i}", "apiKey": "k"} for i in range(1, 4)]
        out = await LoadGenerator(url, tenants, LoadProfile(rate_rps=20), tmp_path / "run.csv").run(2.0)
        await runner.cleanup()
        return out

    rows = list(csv.DictReader(open(asyncio.run(scenario()))))
    assert 80 < len(rows) < 200  # 3 tenants x 20 rps x 2 s = 120 expected
    assert {r["status"] for r in rows} <= {"200", "201"}
    assert {r["op"] for r in rows} >= {"CreateOrder", "GetOrder"}
    assert all(r["cell"] == "c1" for r in rows)
