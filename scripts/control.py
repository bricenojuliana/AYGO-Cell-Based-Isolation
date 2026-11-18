#!/usr/bin/env python3
"""Control-plane administration (CloudShell).

  python3 scripts/control.py mode act        # C+IA: detect and isolate
  python3 scripts/control.py mode observe    # C: detect and audit, never isolate
  python3 scripts/control.py mode off
  python3 scripts/control.py reset           # forget baselines (between experiment runs)
  python3 scripts/control.py audit           # print the audit log
  python3 scripts/control.py export out.json # audit + per-window features, for analysis
"""
import argparse
import json
from decimal import Decimal

import boto3

TABLE = boto3.resource("dynamodb").Table("cellsaas-control")


def _items(pk):
    items, start = [], None
    while True:
        kwargs = {"KeyConditionExpression": "pk = :p", "ExpressionAttributeValues": {":p": pk}}
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = TABLE.query(**kwargs)
        items += page["Items"]
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _json(obj):
    return json.dumps(obj, indent=2, default=lambda v: float(v) if isinstance(v, Decimal) else str(v))


parser = argparse.ArgumentParser()
sub = parser.add_subparsers(dest="cmd", required=True)
sub.add_parser("mode").add_argument("value", choices=["off", "observe", "act"])
sub.add_parser("reset")
sub.add_parser("audit")
sub.add_parser("export").add_argument("path")
args = parser.parse_args()

if args.cmd == "mode":
    boto3.client("ssm").put_parameter(Name="/cellsaas/control/mode", Value=args.value, Type="String", Overwrite=True)
    print(f"mode = {args.value}")
elif args.cmd == "reset":
    with TABLE.batch_writer() as batch:
        for item in _items("BASELINE"):
            batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
    print("baselines cleared")
elif args.cmd == "audit":
    for item in _items("AUDIT"):
        print(f'{item["sk"]}  {item["action"]:10} applied={item["applied"]}  {item["reason"]}')
else:
    with open(args.path, "w") as f:
        f.write(_json({"audit": _items("AUDIT"), "features": _items("FEATURES")}))
    print(f"wrote {args.path}")
