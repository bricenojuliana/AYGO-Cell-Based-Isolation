import pytest

from cellsaas.control.placement import PlacementPolicy


def test_rf06_balances_tenants_and_breaks_ties_by_id():
    policy = PlacementPolicy(["c2", "c1", "c3"])
    assigned = []
    for _ in range(7):
        assigned.append(policy.choose(assigned))
    assert assigned == ["c1", "c2", "c3", "c1", "c2", "c3", "c1"]


def test_rf06_ignores_cells_outside_the_policy_such_as_quarantine():
    assert PlacementPolicy(["c1", "c2"]).choose(["q", "q", "c1"]) == "c2"


def test_requires_cells():
    with pytest.raises(ValueError):
        PlacementPolicy([])
