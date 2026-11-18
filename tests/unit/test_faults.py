import json

from cellsaas.cell.faults import SsmFaultSource
from cellsaas.cell.ports import Fault


class FakeSsm:
    class exceptions:
        class ParameterNotFound(Exception):
            pass

    def __init__(self, value=None, fail=False):
        self.value, self.fail, self.reads = value, fail, 0

    def get_parameter(self, Name):
        self.reads += 1
        if self.fail:
            raise RuntimeError("boom")
        if self.value is None:
            raise self.exceptions.ParameterNotFound()
        return {"Parameter": {"Value": self.value}}


def test_missing_parameter_means_no_fault():
    assert SsmFaultSource(FakeSsm(), "/x", clock=lambda: 0).current() == Fault()


def test_reads_and_clamps_fault_and_caches_it():
    now = [0.0]
    ssm = FakeSsm(json.dumps({"errorRate": 7, "delayMs": -3}))
    source = SsmFaultSource(ssm, "/x", ttl_seconds=5, clock=lambda: now[0])
    assert source.current() == Fault(error_rate=1.0, delay_ms=0)
    source.current()
    assert ssm.reads == 1
    now[0] = 6
    source.current()
    assert ssm.reads == 2


def test_read_errors_keep_last_known_value():
    now = [0.0]
    ssm = FakeSsm(json.dumps({"errorRate": 0.5}))
    source = SsmFaultSource(ssm, "/x", ttl_seconds=1, clock=lambda: now[0])
    assert source.current().error_rate == 0.5
    ssm.fail, now[0] = True, 2
    assert source.current().error_rate == 0.5
