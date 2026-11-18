"""Open-loop load generator (ADR-009 v0.2).

Why not a closed-loop tool such as Locust's default users: a closed-loop client waits for each
response before sending the next request, so when a cell saturates the offered load drops by itself
and the damage to the neighbours is under-measured (coordinated omission). Here every tenant sends
requests on its own Poisson schedule whether or not earlier ones have answered.

Every request is written to a CSV row: sent_at (epoch s), tenant, op, status, latency_ms, cell, cell_ms
(time the router spent waiting for the cell, from the x-cell-ms header).
Status 0 means a client-side timeout or connection error.
"""
from __future__ import annotations

import asyncio
import csv
import json
import random
import time
from pathlib import Path

import aiohttp

from .profile import LoadProfile

ORDER = {"items": [{"sku": "TINTO", "quantity": 2, "unitPriceCents": 250_000},
                   {"sku": "AREPA", "quantity": 1, "unitPriceCents": 600_000}]}


class LoadGenerator:
    def __init__(self, api: str, tenants: list[dict], profile: LoadProfile, out: Path, seed: int = 7,
                 timeout_s: float = 10.0, max_in_flight: int = 3000):
        self._api = api.rstrip("/")
        self._tenants = tenants
        self._profile = profile
        self._out = out
        self._rng = random.Random(seed)
        self._timeout = aiohttp.ClientTimeout(total=timeout_s)
        self._slots = asyncio.Semaphore(max_in_flight)
        self._orders: dict[str, list[str]] = {t["tenantId"]: [] for t in tenants}
        self._rows: list[tuple] = []

    async def run(self, duration_s: float) -> Path:
        self._start = time.time()
        connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=connector, timeout=self._timeout) as session:
            await asyncio.gather(*(self._tenant_loop(session, t, duration_s) for t in self._tenants))
            while self._slots._value < 3000 and time.time() - self._start < duration_s + 15:  # drain in-flight
                await asyncio.sleep(0.2)
        self._write()
        return self._out

    async def _tenant_loop(self, session, tenant: dict, duration_s: float) -> None:
        tasks = set()
        next_at = self._start + self._rng.random()  # spread tenants' first requests
        while next_at - self._start < duration_s:
            delay = next_at - time.time()
            if delay > 0:
                await asyncio.sleep(delay)
            await self._slots.acquire()
            task = asyncio.create_task(self._one(session, tenant))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            next_at += self._profile.next_gap(tenant["tenantId"], next_at - self._start, self._rng)
        if tasks:
            await asyncio.gather(*tasks)

    async def _one(self, session, tenant: dict) -> None:
        tenant_id = tenant["tenantId"]
        orders = self._orders[tenant_id]
        op = self._profile.pick_op(self._rng, bool(orders))
        headers = {"x-api-key": tenant["apiKey"], "content-type": "application/json"}
        if op == "CreateOrder":
            method, url, body = "POST", f"{self._api}/orders", json.dumps(ORDER)
        elif op == "GetOrder":
            method, url, body = "GET", f"{self._api}/orders/{self._rng.choice(orders[-50:])}", None
        else:
            method, url, body = "GET", f"{self._api}/reports/daily", None
        sent = time.time()
        status, cell, cell_ms = 0, "", ""
        try:
            async with session.request(method, url, data=body, headers=headers) as response:
                status, cell = response.status, response.headers.get("x-cell-id", "")
                cell_ms = response.headers.get("x-cell-ms", "")
                payload = await response.read()
                if op == "CreateOrder" and status == 201:
                    orders.append(json.loads(payload)["orderId"])
        except (TimeoutError, aiohttp.ClientError):
            status = 0
        finally:
            self._slots.release()
            self._rows.append((round(sent, 3), tenant_id, op, status, round((time.time() - sent) * 1000, 1), cell, cell_ms))

    def _write(self) -> None:
        self._out.parent.mkdir(parents=True, exist_ok=True)
        with self._out.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["sent_at", "tenant", "op", "status", "latency_ms", "cell", "cell_ms"])
            writer.writerows(sorted(self._rows))
