"""CloudWatch Embedded Metric Format (EMF) emitter: one JSON line per request (ADR-005, SPEC RF07)."""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TextIO


class MetricsEmitter:
    """Writes EMF records to stdout; Lambda ships them to CloudWatch Logs, which extracts the metrics."""

    def __init__(self, namespace: str, stream: TextIO | None = None, clock: Callable[[], float] = time.time):
        self._namespace = namespace
        self._stream = stream or sys.stdout
        self._clock = clock

    def emit(self, dimensions: Mapping[str, str], metrics: Mapping[str, tuple[float, str]],
             dimension_sets: Sequence[Sequence[str]] | None = None, properties: Mapping[str, object] | None = None) -> None:
        """`metrics` maps name -> (value, unit). Every key of each dimension set must be in `dimensions`."""
        sets = [list(s) for s in (dimension_sets or [list(dimensions)])]
        record: dict = {
            "_aws": {
                "Timestamp": int(self._clock() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": self._namespace,
                    "Dimensions": sets,
                    "Metrics": [{"Name": name, "Unit": unit} for name, (_, unit) in metrics.items()],
                }],
            },
            **dict(dimensions),
            **{name: value for name, (value, _) in metrics.items()},
            **dict(properties or {}),
        }
        self._stream.write(json.dumps(record, separators=(",", ":")) + "\n")
