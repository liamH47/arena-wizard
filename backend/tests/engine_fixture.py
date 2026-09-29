"""Synthetic cards, pools, and card values for engine tests. Every number is made up.

Cards are built from a mana cost and a kind, so a test can say exactly what a pool holds
without depending on any real set's card text or statistics.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from arena_wizard.domain.cards import WUBRG, Card, Color, Rarity, sort_colors
from arena_wizard.domain.decks import CardValue
from arena_wizard.domain.pool import Pool, PoolEntry
from arena_wizard.domain.scoring import ScoringConfig, load_scoring_config
from arena_wizard.domain.sets import Format
from arena_wizard.engine.builder import PAIRS, BuildInputs, pair_code
from arena_wizard.engine.values import PairValue

W, U, B, R, G = WUBRG
CONFIG = load_scoring_config(Format.BO1_SEALED)
REMOVAL_TEXT = "Destroy target creature."


def card(
    name: str,
    cost: str,
    *,
    kind: str = "Creature — Test",
    text: str = "",
    rarity: Rarity = Rarity.COMMON,
    produced: tuple[str, ...] = (),
) -> Card:
    """A one-face card with its mana value and colors read from `cost`."""
    symbols = re.findall(r"\{([^}]+)\}", cost)
    mana_value = sum(int(s) if s.isdigit() else 1 for s in symbols)
    letters = [part for s in symbols for part in s.split("/") if part in "WUBRG"]
    colors = sort_colors([Color(c) for c in letters])
    return Card(
        scryfall_id=f"id-{name}",
        oracle_id=f"oracle-{name}",
        arena_id=None,
        name=name,
        front_name=name,
        layout="normal",
        set_code="TST",
        collector_number=name,
        rarity=rarity,
        mana_cost=cost,
        mana_value=float(mana_value),
        type_line=kind,
        oracle_text=text,
        power="2" if kind.startswith("Creature") else None,
        toughness="2" if kind.startswith("Creature") else None,
        colors=colors,
        color_identity=colors,
        produced_mana=produced,
        faces=(),
        image_uri=None,
        artist=None,
        released_at="2026-01-01",
    )


def removal(name: str, cost: str) -> Card:
    """An instant that destroys a creature."""
    return card(name, cost, kind="Instant", text=REMOVAL_TEXT)


def dual(name: str, colors: str) -> Card:
    """A land that taps for either of two colors."""
    a, b = colors[0], colors[1]
    return card(
        name,
        "",
        kind="Land",
        text=f"{{T}}: Add {{{a}}} or {{{b}}}.",
        produced=(a, b),
    )


def make_pool(entries: Iterable[tuple[Card, int]]) -> Pool:
    """A pool of exactly these cards, with no basics and no warnings."""
    return Pool(
        set_code="TST",
        format=Format.BO1_SEALED,
        entries=tuple(PoolEntry(c, n) for c, n in entries),
        basics=(),
        warnings=(),
    )


def value(name: str, q: float, *, games: int = 400, se: float = 2.0) -> CardValue:
    """A card value with made-up rates; `games` 0 makes it a no-data value."""
    if games == 0:
        return CardValue(name, q, None, 0.55, 1.0, 0, "common average", se)
    return CardValue(name, q, 0.56, 0.55, 0.1, games, "made-up source", se)


def no_pairs() -> dict[str, PairValue]:
    """Every pair with no record."""
    return {pair_code(p): PairValue(pair_code(p), 0.0, None, None, None, 0) for p in PAIRS}


def make_inputs(
    pool: Pool,
    q: Mapping[str, float],
    *,
    bombs: Mapping[str, float] | None = None,
    pairs: Mapping[str, PairValue] | None = None,
    config: ScoringConfig = CONFIG,
    se: float = 2.0,
) -> BuildInputs:
    """Builder inputs valuing each pool card at `q[name]` (0 when unnamed)."""
    return BuildInputs(
        values={
            e.card.front_name: value(e.card.front_name, q.get(e.card.front_name, 0.0), se=se)
            for e in pool.entries
        },
        pairs=dict(pairs) if pairs is not None else no_pairs(),
        bombs=dict(bombs or {}),
        config=config,
    )


def three_pair_pool() -> tuple[Pool, dict[str, float]]:
    """A pool where exactly WU, WB, and UB can field 23 spells, and red is splashable.

    White is the deepest color, blue next, black shallowest; the red removal spell is
    strong enough to be worth splashing and the red double-pip creature is not splashable.
    """
    cards: list[tuple[Card, int]] = []
    q: dict[str, float] = {}
    costs = ["{W}", "{1}{W}", "{1}{W}", "{2}{W}", "{2}{W}", "{3}{W}", "{3}{W}", "{4}{W}"]
    costs += ["{1}{W}{W}", "{2}{W}{W}"]
    for color, base in ((W, 6.0), (U, 3.0), (B, 1.0)):
        for i, cost in enumerate(costs):
            name = f"{color.value} Creature {i}"
            cards.append((card(name, cost.replace("W", color.value)), 1))
            q[name] = base - 0.5 * i
    for color, base in ((W, 5.0), (U, -1.0), (B, 4.0)):
        for i, cost in enumerate(["{1}{W}", "{3}{W}"]):
            name = f"{color.value} Removal {i}"
            cards.append((removal(name, cost.replace("W", color.value)), 1))
            q[name] = base - i
    cards.append((removal("B Removal 2", "{4}{B}"), 1))
    q["B Removal 2"] = 3.0
    cards.append((card("WU Gold", "{W}{U}"), 1))
    q["WU Gold"] = 7.0
    cards.append((card("WB Hybrid", "{1}{W/B}"), 2))
    q["WB Hybrid"] = 1.5
    cards.append((removal("R Bolt", "{R}"), 1))
    q["R Bolt"] = 20.0
    cards.append((card("R Giant", "{4}{R}"), 1))
    q["R Giant"] = 2.0
    cards.append((card("R Twin", "{R}{R}"), 1))
    q["R Twin"] = 30.0
    cards.append((card("G Bear", "{1}{G}"), 2))
    q["G Bear"] = -10.0
    return make_pool(cards), q
