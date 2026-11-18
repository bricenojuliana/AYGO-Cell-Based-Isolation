#!/usr/bin/env python3
"""Tenant administration (runs in CloudShell; needs boto3 and the CELLSAAS_PEPPER variable).

  python3 scripts/tenants.py create --count 30 --cells c1,c2,c3   # registers tenants, writes tenants.json
  python3 scripts/tenants.py topology pool                          # every tenant -> pool cell (config P)
  python3 scripts/tenants.py topology cells                         # back to their own cells (configs C, C+IA)
  python3 scripts/tenants.py quarantine cafe-07                     # manual isolation (SPEC RF11)
  python3 scripts/tenants.py release cafe-07
  python3 scripts/tenants.py show

tenants.json holds the API keys in clear for the load generator: keep it out of git.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import boto3  # noqa: E402

from cellsaas.control.placement import PlacementPolicy  # noqa: E402
from cellsaas.routing import RoutingTable, hash_api_key  # noqa: E402

TENANTS_FILE = ROOT / "tenants.json"


def _routing() -> RoutingTable:
    return RoutingTable(boto3.resource("dynamodb").Table(os.environ.get("ROUTING_TABLE_NAME", "cellsaas-routing")))


def _load() -> list[dict]:
    return json.loads(TENANTS_FILE.read_text()) if TENANTS_FILE.exists() else []


def create(args) -> None:
    pepper = os.environ["CELLSAAS_PEPPER"]
    routing, tenants = _routing(), _load()
    policy = PlacementPolicy(args.cells.split(","))
    start = len(tenants)
    for n in range(start, start + args.count):
        tenant_id = f"cafe-{n + 1:02d}"
        api_key = secrets.token_urlsafe(24)
        cell = policy.choose(t["cell"] for t in tenants)
        routing.register(tenant_id, hash_api_key(api_key, pepper), cell)
        tenants.append({"tenantId": tenant_id, "apiKey": api_key, "cell": cell})
    TENANTS_FILE.write_text(json.dumps(tenants, indent=2))
    os.chmod(TENANTS_FILE, 0o600)
    print(f"{args.count} tenants registered; {len(tenants)} in {TENANTS_FILE.name}")


def topology(args) -> None:
    routing = _routing()
    for tenant in _load():
        routing.release(tenant["tenantId"])
        routing.assign(tenant["tenantId"], "pool" if args.mode == "pool" else tenant["cell"])
    print(f"topology = {args.mode}")


def quarantine(args) -> None:
    print("quarantined" if _routing().quarantine(args.tenant, args.cell) else "already quarantined or unknown")


def release(args) -> None:
    print("released" if _routing().release(args.tenant) else "was not quarantined")


def show(_args) -> None:
    for route in sorted(_routing().routes(), key=lambda r: r.tenant_id):
        print(f"{route.tenant_id:10} {route.cell_id:6} {route.status:12} {route.home_cell_id or ''}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("create"); p.add_argument("--count", type=int, default=30)  # noqa: E702
    p.add_argument("--cells", default="c1,c2,c3"); p.set_defaults(func=create)  # noqa: E702
    p = sub.add_parser("topology"); p.add_argument("mode", choices=["pool", "cells"]); p.set_defaults(func=topology)  # noqa: E702
    p = sub.add_parser("quarantine"); p.add_argument("tenant"); p.add_argument("--cell", default="q")  # noqa: E702
    p.set_defaults(func=quarantine)
    p = sub.add_parser("release"); p.add_argument("tenant"); p.set_defaults(func=release)  # noqa: E702
    sub.add_parser("show").set_defaults(func=show)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
