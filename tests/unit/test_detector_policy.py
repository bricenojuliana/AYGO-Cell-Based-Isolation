import pytest

from cellsaas.control.detector import ZScoreDetector
from cellsaas.control.model import Baseline, CellHealth, Score, TenantWindow
from cellsaas.control.policy import IsolationPolicy
from cellsaas.routing import QUARANTINED, Route


def _w(tenant="t1", cell="c1", rps=5.0, cu=5.0, share=0.1):
    return TenantWindow(tenant, cell, rps, cu, share)


def _trained(detector, n=10, **kw):
    baseline = Baseline()
    for i in range(n):
        detector.learn(_w(rps=5 + (i % 2) * 0.2, cu=5 + (i % 2) * 0.2, **kw), baseline)
    return baseline


def test_rf08_not_ready_during_warmup():
    detector = ZScoreDetector(warmup_windows=5)
    baseline = _trained(detector, n=3)
    assert detector.score(_w(rps=500), baseline).ready is False


def test_rf08_normal_window_scores_low_and_spike_scores_high():
    detector = ZScoreDetector()
    baseline = _trained(detector)
    assert detector.score(_w(), baseline).value < 1
    spike = detector.score(_w(rps=50), baseline)
    assert spike.ready and spike.value > 10 and spike.feature == "rps"


def test_std_floor_avoids_explosions_for_perfectly_steady_tenants():
    detector = ZScoreDetector(min_std_ratio=0.1)
    baseline = Baseline()
    for _ in range(10):
        detector.learn(_w(rps=5, cu=5), baseline)
    assert detector.score(_w(rps=5.4, cu=5), baseline).value < 1  # 8 % more is not an anomaly


def test_spec6_attribution_ignores_symptoms_of_victims():
    """A victim's latency explodes but its demand does not: it must not be blamed."""
    detector = ZScoreDetector()
    baseline = _trained(detector)
    assert detector.score(_w(rps=5, cu=5.1), baseline).value < 3


def _setup(streak_t1=2, streak_t2=0, s1=12.0, s2=1.0, cell_bad=True, route_t1=None):
    scores = {"t1": Score("t1", s1, "rps", True), "t2": Score("t2", s2, "rps", True)}
    baselines = {"t1": Baseline(streak=streak_t1), "t2": Baseline(streak=streak_t2)}
    cells = {"c1": CellHealth("c1", 1000, 0, 80 if cell_bad else 0, 200)}
    routes = {"t1": route_t1 or Route("t1", "c1"), "t2": Route("t2", "c1")}
    return scores, baselines, cells, routes


def test_rf08_quarantines_after_k_windows_when_cell_is_degraded():
    decisions = IsolationPolicy(k=2).decide(*_setup(), act=True)
    assert [(d.tenant_id, d.action, d.from_cell) for d in decisions] == [("t1", "QUARANTINE", "c1")]


@pytest.mark.parametrize("kwargs", [{"streak_t1": 1}, {"cell_bad": False},
                                    {"route_t1": Route("t1", "q", QUARANTINED, "c1")}])
def test_no_action_without_streak_symptoms_or_if_already_isolated(kwargs):
    assert IsolationPolicy(k=2).decide(*_setup(**kwargs), act=True) == []


def test_observe_mode_records_but_does_not_act():
    assert IsolationPolicy().decide(*_setup(), act=False)[0].action == "OBSERVE"


def test_at_most_one_tenant_per_cell_per_cycle():
    decisions = IsolationPolicy().decide(*_setup(streak_t2=3, s2=9.0), act=True)
    assert [d.tenant_id for d in decisions] == ["t1"]


def test_streaks_grow_and_reset():
    policy = IsolationPolicy(threshold=3)
    baselines = {"t1": Baseline(streak=1)}
    policy.update_streaks({"t1": Score("t1", 5, "rps", True)}, baselines)
    assert baselines["t1"].streak == 2
    policy.update_streaks({"t1": Score("t1", 1, "rps", True)}, baselines)
    assert baselines["t1"].streak == 0


def test_cell_health_symptoms():
    assert CellHealth("c", 100, 2, 0, 100).symptomatic(500, 0.01)
    assert CellHealth("c", 100, 0, 0, 900).symptomatic(500, 0.01)
    assert not CellHealth("c", 100, 0, 0, 100).symptomatic(500, 0.01)
    assert not CellHealth("c", 0, 0, 0, 0).symptomatic(500, 0.01)
