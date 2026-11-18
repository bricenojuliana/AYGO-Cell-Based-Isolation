"""Metrics on synthetic runs where the right answer is known."""
import numpy as np
import pandas as pd

from experiments.cellexp.metrics import cliffs_delta, run_metrics

META = {"run": "x", "config": "CIA", "scenario": "E1", "rep": 1, "started_at": 1000.0,
        "fault_start_s": 120, "fault_end_s": 420, "noisy_tenant": "cafe-01"}


def _df(affected_tenants, bad_from=120, bad_to=420):
    rows = []
    for tenant in [f"cafe-{i:02d}" for i in range(1, 11)]:
        for t in np.arange(0, 480, 0.5):
            hit = tenant in affected_tenants and bad_from <= t < bad_to
            rows.append((t, tenant, 503 if hit else 201, 50.0, 20.0))
    df = pd.DataFrame(rows, columns=["t", "tenant", "status", "latency_ms", "cell_ms"])
    df["sent_at"] = df["t"] + 1000
    df["bad"] = (df["status"] >= 500)
    df["window"] = (df["t"] // 60).astype(int)
    return df


def test_counts_affected_victims_excluding_the_noisy_tenant():
    m = run_metrics(_df({"cafe-01", "cafe-02", "cafe-03"}), META)
    assert m.victims == 9
    assert m.affected_peak_pct == round(2 / 9 * 100, 1)
    assert m.routing_overhead_p50_ms == 30.0


def test_mttr_is_when_victims_recover_for_two_windows():
    m = run_metrics(_df({"cafe-02"}, bad_to=240), META)
    assert m.mttr_s == 120.0  # recovered at minute 4 (240 s), fault began at 120 s


def test_mttr_none_if_never_recovered_and_zero_if_never_affected():
    assert run_metrics(_df({"cafe-02"}, bad_to=480), META).mttr_s is None
    assert run_metrics(_df(set()), META).mttr_s == 0.0


def test_mttd_from_first_applied_quarantine():
    meta = {**META, "audit": [{"sk": "1970-01-01T00:20:40.000000Z#cafe-01", "action": "QUARANTINE", "applied": True}]}
    assert run_metrics(_df(set()), meta).mttd_s == 1240 - 1120


def test_cliffs_delta():
    assert cliffs_delta([3, 4], [1, 2]) == 1.0
    assert cliffs_delta([1, 2], [1, 2]) == 0.0
