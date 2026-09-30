from __future__ import annotations

import pytest

from arena_wizard.domain.decks import CardValue, ValueBasis
from arena_wizard.engine.adjust import Adjustment, apply_adjustments

VALUES = {"A": CardValue("A", 10.0, None, None, None, 0, "grades", 1.0, ValueBasis.GRADES)}


@pytest.mark.parametrize(
    ("adjustment", "q", "bombs"),
    [
        (Adjustment("A", None, 2.5, "", "Alice"), 12.5, {"B": 3.0}),
        (Adjustment("Z", None, 2.5, "", "Alice"), 10.0, {"B": 3.0}),  # not in the pool
        (Adjustment("A", "add", None, "", "Alice"), 10.0, {"A": 2.0, "B": 3.0}),
        (Adjustment("B", "add", None, "", "Alice"), 10.0, {"B": 3.0}),  # keeps its score
        (Adjustment("B", "remove", None, "", "Alice"), 10.0, {}),
    ],
)
def test_adjustments_win_over_the_engines_values_and_bombs(
    adjustment: Adjustment, q: float, bombs: dict[str, float]
) -> None:
    values, adjusted = apply_adjustments(VALUES, {"B": 3.0}, [adjustment], 2.0)
    assert values["A"].q == q
    assert values["A"].adjustment == ((2.5, "Alice") if q != 10.0 else None)
    assert adjusted == bombs
