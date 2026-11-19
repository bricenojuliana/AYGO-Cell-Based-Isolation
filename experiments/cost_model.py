#!/usr/bin/env python3
"""Monthly cost model at nominal load (H4). Public us-east-1 list prices; verify before quoting.

Compares a real pool (no router), cells (router + 3 cells + quarantine cell, same total capacity) and
cells + detector. Writes results/costos.csv.
"""
from pathlib import Path

import pandas as pd

HOURS = 730
PRICE = {  # USD, us-east-1 list prices (verify: aws.amazon.com/<service>/pricing)
    "apigw_http_per_m": 1.00, "lambda_req_per_m": 0.20, "lambda_gbs_arm": 0.0000133334,
    "ddb_wcu_h": 0.00065, "ddb_rcu_h": 0.00013, "logs_gb": 0.50, "metric_month": 0.30, "gmd_per_1000": 0.01,
}
LOAD = {"rps": 60.0}  # 30 tenants x 2 rps
REQ_M = LOAD["rps"] * 3600 * HOURS / 1e6  # million requests per month
ASSUME = {
    "router_ms": 30, "router_gb": 0.5, "cell_ms": 20, "cell_gb": 0.25,
    "log_kb_per_invocation": 0.9,  # EMF line + START/END/REPORT lines
    "metrics_pool": 186, "metrics_cells": 204, "metrics_router": 140,  # custom metrics (dimension combinations)
    "detector_metrics_per_min": 106, "detector_runs_per_month": 60 * HOURS,
}


def lambda_cost(ms, gb, invocations_m):
    return invocations_m * PRICE["lambda_req_per_m"] + invocations_m * 1e6 * ms / 1000 * gb * PRICE["lambda_gbs_arm"]


def rows():
    apigw = REQ_M * PRICE["apigw_http_per_m"]
    cell = lambda_cost(ASSUME["cell_ms"], ASSUME["cell_gb"], REQ_M)
    router = lambda_cost(ASSUME["router_ms"], ASSUME["router_gb"], REQ_M)
    ddb = (100 * PRICE["ddb_wcu_h"] + 100 * PRICE["ddb_rcu_h"]) * HOURS  # equal total capacity in every topology
    logs_one = REQ_M * 1e6 * ASSUME["log_kb_per_invocation"] / 1e6 * PRICE["logs_gb"]  # GB per million x price
    detector_gmd = ASSUME["detector_metrics_per_min"] * ASSUME["detector_runs_per_month"] / 1000 * PRICE["gmd_per_1000"]
    pool = {"API Gateway": apigw, "Lambda celdas": cell, "Lambda router": 0.0, "DynamoDB": ddb, "CloudWatch Logs": logs_one,
            "Métricas personalizadas": ASSUME["metrics_pool"] * PRICE["metric_month"], "Detector (GetMetricData)": 0.0}
    cells = {**pool, "Lambda router": router, "CloudWatch Logs": 2 * logs_one,
             "Métricas personalizadas": (ASSUME["metrics_cells"] + ASSUME["metrics_router"]) * PRICE["metric_month"]}
    cia = {**cells, "Detector (GetMetricData)": detector_gmd}
    return {"Pool sin router": pool, "Celdas": cells, "Celdas + IA": cia}


def main():
    table = pd.DataFrame(rows()).round(2)
    table.loc["Total"] = table.sum().round(2)
    base = table.loc["Total", "Pool sin router"]
    table.loc["Sobrecosto vs pool (%)"] = ((table.loc["Total"] / base - 1) * 100).round(1)
    out = Path(__file__).resolve().parents[1] / "results" / "costos.csv"
    table.to_csv(out)
    print(f"Carga: {LOAD['rps']} rps = {REQ_M:.1f} M peticiones/mes")
    print(table.to_string())


if __name__ == "__main__":
    main()
