"""The group's card adjustments: bombs added or removed, values nudged (decision 0011)."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from arena_wizard.domain.decks import CardValue


@dataclass(frozen=True, slots=True)
class Adjustment:
    """One card's adjustment: `bomb` is "add", "remove", or None; `q_delta` is in points."""

    name: str
    bomb: str | None
    q_delta: float | None
    note: str
    by: str


def apply_adjustments(
    values: Mapping[str, CardValue],
    bombs: Mapping[str, float],
    adjustments: Sequence[Adjustment],
    threshold: float,
) -> tuple[dict[str, CardValue], dict[str, float]]:
    """Apply adjustments over the engine's values and bombs; they win over both. Pure."""
    values, bombs = dict(values), dict(bombs)
    for a in adjustments:
        if a.q_delta and a.name in values:
            v = values[a.name]
            values[a.name] = dataclasses.replace(v, q=v.q + a.q_delta, adjustment=(a.q_delta, a.by))
        if a.bomb == "add":
            bombs[a.name] = max(bombs.get(a.name, threshold), threshold)
        elif a.bomb == "remove":
            bombs.pop(a.name, None)
    return values, bombs
