from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from arena_wizard.domain.cards import Color
from arena_wizard.engine.mana import (
    ManaCost,
    can_cast,
    castable_cost,
    color_weight,
    dependable_colors,
    parse_mana_cost,
    requirements,
)
from arena_wizard.sources.scryfall import compute_card
from tests.unit.test_lands import card, land

W, U, B, R, G = Color.WHITE, Color.BLUE, Color.BLACK, Color.RED, Color.GREEN


@pytest.mark.parametrize(
    ("cost", "pips", "hybrid"),
    [
        ("{2}{W}{W}", {W: 2}, ()),
        ("{1}{W/B}", {}, (frozenset({W, B}),)),
        ("{X}{U}{R}", {U: 1, R: 1}, ()),
        ("{1}{B/P}", {}, ()),
        ("{2/W}{2/W}", {}, ()),
        ("{C}{3}", {}, ()),
        ("", {}, ()),
    ],
)
def test_costs_parse_into_color_needs(
    cost: str, pips: dict[Color, int], hybrid: tuple[Any, ...]
) -> None:
    assert parse_mana_cost(cost) == ManaCost(pips=pips, hybrid=hybrid)


def test_a_hybrid_card_is_castable_by_either_of_its_colors_but_not_by_neither() -> None:
    cost = parse_mana_cost("{W/B}")
    assert can_cast(cost, [W, U]) and can_cast(cost, [B, G])
    assert not can_cast(cost, [U, R])


def test_every_pip_color_must_be_available() -> None:
    assert not can_cast(parse_mana_cost("{1}{W}{B}"), [W, U])
    assert can_cast(parse_mana_cost("{1}{W}{B}"), [W, U, B])


def test_hybrid_needs_go_to_the_better_supplied_color_ties_in_wubrg_order() -> None:
    cost = parse_mana_cost("{W/B}{W/B}")
    assert requirements(cost, {W: 3, B: 9}) == {B: 2}
    assert requirements(cost, {W: 8, B: 8}) == {W: 2}


def test_a_two_part_card_is_cast_for_its_front_face(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    card = compute_card(scryfall_cards["adventure"])
    assert castable_cost(card) == parse_mana_cost(card.faces[0].mana_cost)


def test_color_weight_counts_pips_and_weights_cheap_spells(
    scryfall_cards: dict[str, dict[str, Any]],
) -> None:
    card = compute_card(scryfall_cards["normal"])
    cheap = dataclasses.replace(card, mana_cost="{W}{W}", faces=(), mana_value=2.0)
    dear = dataclasses.replace(card, mana_cost="{4}{B}", faces=(), mana_value=5.0)
    hybrid = dataclasses.replace(card, mana_cost="{W/B}", faces=(), mana_value=1.0)
    weight = color_weight([(cheap, 2), (dear, 1), (hybrid, 1)], [W, B])
    assert weight == {W: 2 * 2 * 1.5 + 0.75, B: 1.0 + 0.75}


def test_a_spell_without_a_mana_cost_is_cast_for_its_suspend_cost() -> None:
    living_end = card(
        "Test Living End",
        text="Suspend 3—{2}{B}{B} (Rather than cast this card from your hand, ...)",
        colors=(B,),
    )
    assert castable_cost(living_end) == ManaCost(pips={B: 2}, hybrid=())


def test_a_suspend_cost_written_with_a_hyphen_also_parses() -> None:
    hyphen = card("Test Hyphen Suspend", text="Suspend 4-{1}{G}", colors=(G,))
    assert castable_cost(hyphen) == ManaCost(pips={G: 1}, hybrid=())


def test_a_costless_spell_without_suspend_needs_one_source_of_each_of_its_colors() -> None:
    costless = card("Test Costless", text="This spell can't be cast normally.", colors=(W, B))
    assert castable_cost(costless) == ManaCost(pips={W: 1, B: 1}, hybrid=())
    assert not can_cast(castable_cost(costless), [W, U])


def test_a_colorless_costless_card_needs_nothing() -> None:
    assert castable_cost(land("Test Wastes", ("C",))) == ManaCost(pips={}, hybrid=())


def test_a_dual_land_dependably_makes_its_two_colors_and_not_colorless() -> None:
    assert dependable_colors(land("Test Dual", ("W", "B", "C"))) == {W, B}


@pytest.mark.parametrize(
    "text",
    [
        "{T}: Add one mana of any color. Spend this mana only to cast an instant or sorcery.",
        "As this land enters, choose a color. {T}: Add one mana of the chosen color.",
    ],
)
def test_a_land_with_restricted_mana_makes_no_dependable_colors(text: str) -> None:
    assert dependable_colors(land("Test Restricted", ("W", "U", "B", "R", "G"), text)) == set()


def test_color_weight_ignores_colors_and_hybrids_outside_the_counted_colors() -> None:
    red = card("Test Red", "{R}{R}", 2.0)
    hybrid = card("Test Hybrid", "{R/G}", 1.0)
    assert color_weight([(red, 1), (hybrid, 2)], [W, B]) == {W: 0.0, B: 0.0}
