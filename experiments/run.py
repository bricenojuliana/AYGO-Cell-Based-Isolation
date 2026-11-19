#!/usr/bin/env python3
"""Runs the experiment matrix (SPEC 7, plan v0.2) from a machine with AWS credentials of the lab.

  python3 experiments/run.py --api "$API" --reps 3            # whole matrix, resumable
  python3 experiments/run.py --api "$API" --only C-E1 --reps 1 # one quick trial run

Each run: set topology and control mode -> wait for route caches -> 2 min normal -> fault (noisy
tenant or failed cell) for 5 min -> 1 min recovery. Writes results/raw/<run>.csv (one row per request)
and results/raw/<run>.json (timestamps, configuration and the detector's audit records).
Runs whose files exist are skipped, so the script can be restarted after a lab session expires.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import zlib
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

import boto3  # noqa: E402

from cellsaas.routing import RoutingTable  # noqa: E402
from experiments.cellexp.loadgen import LoadGenerator  # noqa: E402
from experiments.cellexp.profile import LoadProfile, NoisyPhase  # noqa: E402

MATRIX = [("P", "E0"), ("C", "E0"), ("P", "E1"), ("C", "E1"), ("CIA", "E1"), ("P", "E4"), ("C", "E4")]
MODE = {"P": "off", "C": "observe", "CIA": "act"}
NOISY_TENANT, FAILED_CELL = "cafe-01", "c2"


def set_topology(routing: RoutingTable, tenants: list[dict], config: str) -> None:
    for t in tenants:
        routing.release(t["tenantId"])
        routing.assign(t["tenantId"], "pool" if config == "P" else t["cell"])


def set_fault(ssm, cell: str, on: bool) -> float:
    name = f"/cellsaas/faults/{cell}"
    if on:
        ssm.put_parameter(Name=name, Value=json.dumps({"errorRate": 1.0, "delayMs": 0}), Type="String", Overwrite=True)
    else:
        try:
            ssm.delete_parameter(Name=name)
        except ssm.exceptions.ParameterNotFound:
            pass
    return time.time()


def audit_between(table, start: float, end: float) -> list[dict]:
    items = table.query(KeyConditionExpression="pk = :p", ExpressionAttributeValues={":p": "AUDIT"})["Items"]
    lo, hi = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(start)), time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(end))
    return [json.loads(json.dumps(i, default=lambda v: float(v) if isinstance(v, Decimal) else str(v)))
            for i in items if lo <= i["sk"][:19] <= hi]


async def one_run(args, config, scenario, rep, tenants, routing, ssm, ssm_mode, control) -> None:
    name = f"{config}-{scenario}-r{rep}"
    csv_path, meta_path = args.out / f"{name}.csv", args.out / f"{name}.json"
    if meta_path.exists():
        print(f"skip {name}")
        return
    print(f"== {name}")
    set_topology(routing, tenants, config)
    ssm_mode.put_parameter(Name="/cellsaas/control/mode", Value=MODE[config], Type="String", Overwrite=True)
    for cell in ("c1", "c2", "c3", "q", "pool"):
        set_fault(ssm, cell, False)
    time.sleep(args.settle)  # route caches (10 s) and fault caches (5 s) expire

    noisy = NoisyPhase(NOISY_TENANT, args.fault_start, args.fault_end, args.multiplier) if scenario == "E1" else None
    profile = LoadProfile(rate_rps=args.rate, noisy=noisy)
    generator = LoadGenerator(args.api, tenants, profile, csv_path, seed=zlib.crc32(name.encode()) % 10_000)
    meta = {"run": name, "config": config, "scenario": scenario, "rep": rep, "rate_rps": args.rate,
            "duration_s": args.duration, "fault_start_s": args.fault_start, "fault_end_s": args.fault_end,
            "noisy_tenant": NOISY_TENANT if scenario == "E1" else None,
            "failed_cell": (("pool" if config == "P" else FAILED_CELL) if scenario == "E4" else None),
            "tenant_cells": {t["tenantId"]: ("pool" if config == "P" else t["cell"]) for t in tenants}}

    async def fault_switch():
        if scenario != "E4":
            return
        await asyncio.sleep(args.fault_start)
        meta["fault_on_at"] = set_fault(ssm, meta["failed_cell"], True)
        await asyncio.sleep(args.fault_end - args.fault_start)
        meta["fault_off_at"] = set_fault(ssm, meta["failed_cell"], False)

    meta["started_at"] = time.time()
    await asyncio.gather(generator.run(args.duration), fault_switch())
    meta["ended_at"] = time.time()
    time.sleep(90)  # let the detector process the last windows
    meta["audit"] = audit_between(control, meta["started_at"], time.time())
    set_topology(routing, tenants, config)
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"   done: {csv_path.name}, {len(meta['audit'])} audit records")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", required=True)
    parser.add_argument("--tenants", type=Path, default=ROOT / "tenants.json")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "raw")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--only", help="run a single cell of the matrix, e.g. C-E1")
    parser.add_argument("--rate", type=float, default=2.0, help="requests per second per tenant")
    parser.add_argument("--multiplier", type=float, default=50.0)
    parser.add_argument("--duration", type=float, default=480)
    parser.add_argument("--fault-start", type=float, default=120)
    parser.add_argument("--fault-end", type=float, default=420)
    parser.add_argument("--settle", type=float, default=30)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tenants = json.loads(args.tenants.read_text())
    ddb = boto3.resource("dynamodb")
    routing, control = RoutingTable(ddb.Table("cellsaas-routing")), ddb.Table("cellsaas-control")
    ssm = boto3.client("ssm")
    matrix = [tuple(args.only.split("-"))] if args.only else MATRIX
    runs = [(c, s, r) for r in range(1, args.reps + 1) for c, s in matrix]
    random.Random(args.seed).shuffle(runs)  # randomized order (SPEC 7)
    for config, scenario, rep in runs:
        asyncio.run(one_run(args, config, scenario, rep, tenants, routing, ssm, ssm, control))


if __name__ == "__main__":
    main()
