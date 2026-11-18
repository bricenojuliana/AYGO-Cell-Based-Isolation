import io
import json

import pytest

from cellsaas.router.invoker import CellInvoker, CellUnavailable


class FakeLambda:
    class exceptions:
        class TooManyRequestsException(Exception):
            pass

    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    def invoke(self, FunctionName, Payload):
        self.calls.append((FunctionName, json.loads(Payload)))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_invokes_cell_function_by_name_and_returns_payload():
    client = FakeLambda({"Payload": io.BytesIO(b'{"status": 201, "body": {}}')})
    assert CellInvoker(client).invoke("c2", {"op": "x"}) == {"status": 201, "body": {}}
    assert client.calls == [("cellsaas-cell-c2", {"op": "x"})]


@pytest.mark.parametrize("outcome, status", [
    (FakeLambda.exceptions.TooManyRequestsException(), 429),
    (RuntimeError("network"), 503),
    ({"FunctionError": "Unhandled", "Payload": io.BytesIO(b"{}")}, 502),
])
def test_failures_become_cell_unavailable(outcome, status):
    with pytest.raises(CellUnavailable) as error:
        CellInvoker(FakeLambda(outcome)).invoke("c1", {})
    assert error.value.status == status
