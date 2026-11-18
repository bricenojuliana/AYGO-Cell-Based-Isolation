import random

from experiments.cellexp.profile import LoadProfile, NoisyPhase


def test_noisy_phase_multiplies_only_the_noisy_tenant_inside_the_window():
    profile = LoadProfile(rate_rps=2, noisy=NoisyPhase("cafe-01", 120, 480, 10))
    assert profile.rate("cafe-01", 100) == 2
    assert profile.rate("cafe-01", 200) == 20
    assert profile.rate("cafe-02", 200) == 2
    assert profile.rate("cafe-01", 480) == 2


def test_poisson_gaps_average_to_the_rate():
    rng = random.Random(1)
    profile = LoadProfile(rate_rps=4)
    gaps = [profile.next_gap("t", 0, rng) for _ in range(20000)]
    assert abs(sum(gaps) / len(gaps) - 0.25) < 0.01


def test_operation_mix_and_first_request_is_a_create():
    rng = random.Random(2)
    profile = LoadProfile()
    assert profile.pick_op(random.Random(0), has_orders=False) in {"CreateOrder", "DailyReport"}
    ops = [profile.pick_op(rng, True) for _ in range(20000)]
    assert abs(ops.count("CreateOrder") / len(ops) - 0.8) < 0.02
    assert abs(ops.count("DailyReport") / len(ops) - 0.05) < 0.01
