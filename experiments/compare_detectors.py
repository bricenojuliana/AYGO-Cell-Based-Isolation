#!/usr/bin/env python3
"""z-score vs Isolation Forest on the windows the control loop saved during the matrix (ADR-006).

  python3 scripts/control.py export results/raw/control.json
  python3 experiments/compare_detectors.py      # -> results/detectors.csv

Without the control export (e.g. the account is gone), use the client-side tenant-minutes instead:

  python3 experiments/compare_detectors.py --client results/tenant_minutes.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from experiments.cellexp.offline import CLIENT_FEATURES, client_frame, evaluate, label, windows_frame  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, default=ROOT / "results" / "raw" / "control.json")
    parser.add_argument("--raw", type=Path, default=ROOT / "results" / "raw")
    parser.add_argument("--client", type=Path, help="tenant_minutes.csv recorded by the load generator")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "detectors.csv")
    args = parser.parse_args()
    if args.client:
        frame = client_frame(pd.read_csv(args.client))
        table = pd.DataFrame([asdict(r) for r in evaluate(frame, features=CLIENT_FEATURES)])
        table.insert(0, "source", "client")
        table.to_csv(args.out, index=False)
        print(table.to_string(index=False))
        return
    export = json.loads(args.export.read_text())
    runs = [json.loads(p.read_text()) for p in sorted(args.raw.glob("*-E*-r*.json"))]
    frame = label(windows_frame(export["features"]), runs)
    table = pd.DataFrame([asdict(r) for r in evaluate(frame)])
    table.to_csv(args.out, index=False)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
