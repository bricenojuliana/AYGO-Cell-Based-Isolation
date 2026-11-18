"""Tenant placement policy (SPEC RF06): the active cell with fewest tenants; ties go to the lowest id.
The quarantine cell never receives new tenants."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence


class PlacementPolicy:
    def __init__(self, active_cells: Sequence[str]):
        if not active_cells:
            raise ValueError("At least one active cell is required.")
        self._cells = sorted(active_cells)

    def choose(self, current_assignments: Iterable[str]) -> str:
        load = Counter(cell for cell in current_assignments if cell in self._cells)
        return min(self._cells, key=lambda cell: (load[cell], cell))
