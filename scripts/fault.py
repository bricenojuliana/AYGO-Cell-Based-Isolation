#!/usr/bin/env python3
"""Turns an injected fault on or off for one cell (SPEC RF12). Cells pick it up within ~5 s.

  python3 scripts/fault.py c2 --error-rate 1.0     # cell c2 fails every request (scenario E4)
  python3 scripts/fault.py c2 --delay-ms 300
  python3 scripts/fault.py c2 --off
"""
import argparse
import json
import time

import boto3

parser = argparse.ArgumentParser()
parser.add_argument("cell")
parser.add_argument("--error-rate", type=float, default=0.0)
parser.add_argument("--delay-ms", type=int, default=0)
parser.add_argument("--off", action="store_true")
args = parser.parse_args()

ssm, name = boto3.client("ssm"), f"/cellsaas/faults/{args.cell}"
if args.off:
    try:
        ssm.delete_parameter(Name=name)
    except ssm.exceptions.ParameterNotFound:
        pass
    print(f"{time.time():.3f} fault OFF {args.cell}")
else:
    value = json.dumps({"errorRate": args.error_rate, "delayMs": args.delay_ms})
    ssm.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)
    print(f"{time.time():.3f} fault ON {args.cell} {value}")
