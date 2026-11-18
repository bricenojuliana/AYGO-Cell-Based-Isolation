"""Fault injection switch read from SSM Parameter Store, cached briefly (SPEC RF12, ADR-009).

Parameter /cellsaas/faults/<cellId> holds JSON such as {"errorRate": 1.0, "delayMs": 0}.
A missing parameter means no fault. The switch never fails a request: on any read error it keeps
the last known value.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from .ports import Fault


class SsmFaultSource:
    def __init__(self, ssm_client: Any, parameter_name: str, ttl_seconds: float = 5.0,
                 clock: Callable[[], float] = time.monotonic):
        self._ssm = ssm_client
        self._name = parameter_name
        self._ttl = ttl_seconds
        self._clock = clock
        self._value = Fault()
        self._expires = 0.0

    def current(self) -> Fault:
        now = self._clock()
        if now >= self._expires:
            self._value = self._read()
            self._expires = now + self._ttl
        return self._value

    def _read(self) -> Fault:
        try:
            raw = self._ssm.get_parameter(Name=self._name)["Parameter"]["Value"]
            data = json.loads(raw)
            return Fault(error_rate=min(max(float(data.get("errorRate", 0.0)), 0.0), 1.0),
                         delay_ms=max(int(data.get("delayMs", 0)), 0))
        except self._ssm.exceptions.ParameterNotFound:
            return Fault()
        except Exception:  # noqa: BLE001 - a broken switch must not break the cell
            return self._value
