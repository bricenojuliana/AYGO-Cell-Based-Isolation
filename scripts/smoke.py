#!/usr/bin/env python3
"""Smoke test against the deployed API: create, read, report, cross-tenant isolation, bad key.

  python3 scripts/smoke.py https://xxxx.execute-api.us-east-1.amazonaws.com
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = sys.argv[1].rstrip("/")
TENANTS = json.loads((Path(__file__).resolve().parents[1] / "tenants.json").read_text())


def call(method, path, key, body=None):
    request = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"x-api-key": key, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.headers.get("x-cell-id"), json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, error.headers.get("x-cell-id"), json.loads(error.read() or b"{}")


def check(name, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    return ok


a, b = TENANTS[0], TENANTS[1]
order = {"items": [{"sku": "TINTO", "quantity": 2, "unitPriceCents": 250000}]}
results = []
status, cell, body = call("POST", "/orders", a["apiKey"], order)
results.append(check("create", status == 201 and body.get("totalCents") == 500000, f"{status} cell={cell} {body}"))
order_id = body.get("orderId", "")
status, cell, body = call("GET", f"/orders/{order_id}", a["apiKey"])
results.append(check("read own order", status == 200, f"{status} cell={cell}"))
status, cell, body = call("GET", f"/orders/{order_id}", b["apiKey"])
results.append(check("other tenant cannot read it (QAS05)", status == 404, f"{status} cell={cell}"))
status, cell, body = call("GET", "/reports/daily", a["apiKey"])
results.append(check("daily report", status == 200 and body.get("orders", 0) >= 1, f"{status} {body}"))
status, _, _ = call("GET", "/reports/daily", "not-a-key")
results.append(check("bad key rejected", status == 401, str(status)))
sys.exit(0 if all(results) else 1)
