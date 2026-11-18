"""Synchronous invocation of a cell's Lambda function (ADR-003)."""
from __future__ import annotations

import json
from typing import Any


class CellUnavailable(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


class CellInvoker:
    def __init__(self, lambda_client: Any, function_name_prefix: str = "cellsaas-cell-"):
        self._lambda = lambda_client
        self._prefix = function_name_prefix

    def function_name(self, cell_id: str) -> str:
        return f"{self._prefix}{cell_id}"

    def invoke(self, cell_id: str, request: dict) -> dict:
        try:
            response = self._lambda.invoke(FunctionName=self.function_name(cell_id),
                                           Payload=json.dumps(request).encode())
        except self._lambda.exceptions.TooManyRequestsException as error:
            raise CellUnavailable(429, "CELL_THROTTLED") from error
        except Exception as error:  # noqa: BLE001 - any invoke failure is the cell being unavailable
            raise CellUnavailable(503, "CELL_UNAVAILABLE") from error
        if response.get("FunctionError"):
            raise CellUnavailable(502, "CELL_FAILED")
        return json.loads(response["Payload"].read())
