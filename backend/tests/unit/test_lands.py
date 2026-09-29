from __future__ import annotations

import pytest

from arena_wizard.domain.cards import Card, Color, Rarity
from arena_wizard.domain.decks import LandEntry
from arena_wizard.engine.lands import _split_basics, build_manabase, land_count

W, U, B, R, G = Color.WHITE, Color.BLUE, Color.BLACK, Color.RED, Color.GREEN


def card(
    name: str,
    cost: str = "",
    mana_value: float = 0.0,
    *,
    type_line: str = "Creature — Test",
    text: str = "",
    produced: tuple[str, ...] = (),
    colors: tuple[Color, ...] = (),
    rarity: Rarity = Rarity.COMMON,
) -> Card:
    """A made-up card with only the fields the engine reads."""
    return Card(
        scryfall_id=name,
        oracle_id=name,
        arena_id=None,
        name=name,
        front_name=name,
        layout="normal",
        set_code="TST",
        collector_number="1",
        rarity=rarity,
        mana_cost=cost,
        mana_value=mana_value,
        type_line=type_line,
        oracle_text=text,
        power=None,
        toughness=None,
        colors=colors,
        color_identity=colors,
        produced_mana=produced,
        faces=(),
        image_uri=None,
        artist=None,
        released_at="2026-01-01",
    )


def land(name: str, produced: tuple[str, ...], text: str = "") -> Card:
    """A made-up non-basic land."""
    return card(name, type_line="Land", text=text, produced=produced)


WHITE_TWO = card("White Two", "{W}{W}", 2.0)  # weight 2 pips * 1.5 per copy
BLACK_FOUR = card("Black Four", "{3}{B}", 4.0)  # weight 1 per copy
SPELLS = [(WHITE_TWO, 6), (BLACK_FOUR, 3)]  # W 18, B 3
BARRENS = land("Test Barrens", ("W", "B"), "{T}: Add {W} or {B}.")
GREAT_HALL = land(
    "Test Great Hall",
    ("W", "U", "B", "R", "G"),
    "{T}: Add one mana of any color. Spend this mana only to cast an instant or sorcery spell.",
)
ROOM = land("Test Room", ("W", "U", "B", "R", "G"), "As this enters, choose a color.")
OFF_COLOR = land("Test Island Mountain", ("U", "R"))
TRI_LAND = land("Test Tri", ("W", "B", "R"), "{T}: Add {W}, {B}, or {R}.")


def test_no_spells_play_seventeen_lands() -> None:
    assert land_count([]) == 17


def test_a_low_curve_with_few_expensive_spells_plays_sixteen() -> None:
    cheap, five = card("Cheap", "{W}", 2.0), card("Five", "{4}{W}", 5.0)
    assert land_count([(cheap, 21), (five, 2)]) == 16  # average (42 + 10) / 23 = 2.26


def test_a_low_average_with_three_expensive_spells_still_plays_seventeen() -> None:
    cheap, five = card("Cheap", "{W}", 1.0), card("Five", "{4}{W}", 5.0)
    assert land_count([(cheap, 20), (five, 3)]) == 17


def test_an_average_of_exactly_two_point_seven_plays_seventeen() -> None:
    two, three = card("Two", "{W}", 2.0), card("Three", "{2}{W}", 3.0)
    assert land_count([(two, 3), (three, 7)]) == 17  # (6 + 21) / 10 = 2.7


def test_the_lighter_color_is_raised_to_six_sources() -> None:
    # share 3/12 of 17 is 4.25, rounded to 4, raised to the floor of 6
    assert _split_basics({W: 9.0, B: 3.0}, {W: 0, B: 0}, 17) == {W: 11, B: 6}


def test_equal_weights_split_evenly_with_the_odd_basic_by_bankers_rounding() -> None:
    # W sorts first on a tie, so B is the lighter; round(8.5) is 8
    assert _split_basics({W: 6.0, B: 6.0}, {W: 0, B: 0}, 17) == {W: 9, B: 8}


def test_no_colored_pips_split_evenly_without_a_floor() -> None:
    assert _split_basics({W: 0.0, B: 0.0}, {W: 0, B: 0}, 16) == {W: 8, B: 8}


def test_a_color_no_spell_uses_gets_no_basics() -> None:
    assert _split_basics({W: 10.0, B: 0.0}, {W: 0, B: 0}, 17) == {W: 17, B: 0}


def test_dual_sources_count_toward_each_colors_share() -> None:
    # 15 basics + 2 + 2 duals = 19 sources; B's half is round(9.5) = 10, less its 2 duals
    assert _split_basics({W: 5.0, B: 5.0}, {W: 2, B: 2}, 15) == {W: 7, B: 8}


def test_duals_that_already_cover_the_lighter_color_leave_it_no_basics() -> None:
    assert _split_basics({W: 10.0, B: 1.0}, {W: 0, B: 8}, 9) == {W: 9, B: 0}


def test_the_floor_never_takes_more_basics_than_there_are() -> None:
    assert _split_basics({W: 1.0, B: 1.0}, {W: 0, B: 0}, 3) == {W: 0, B: 3}


def test_a_two_color_deck_without_duals_splits_basics_by_pips() -> None:
    manabase = build_manabase(SPELLS, (W, B), None, [], 17)
    assert manabase.lands == (LandEntry("Plains", W, 11), LandEntry("Swamp", B, 6))
    assert manabase.sources == {W: 11, B: 6}


def test_only_duals_that_always_make_both_colors_go_in_first() -> None:
    pool_lands = [(BARRENS, 2), (GREAT_HALL, 1), (ROOM, 1), (OFF_COLOR, 1)]
    manabase = build_manabase(SPELLS, (W, B), None, pool_lands, 17)
    # 15 basics; B's share of 17 sources rounds to 2, less 2 duals, raised to 6 - 2 = 4
    assert manabase.lands == (
        LandEntry("Test Barrens", None, 2),
        LandEntry("Plains", W, 11),
        LandEntry("Swamp", B, 4),
    )
    assert manabase.sources == {W: 13, B: 6}


def test_duals_stop_when_the_land_slots_are_full_and_no_basics_are_added() -> None:
    second = land("Second Barrens", ("W", "B"))
    manabase = build_manabase(SPELLS, (W, B), None, [(BARRENS, 3), (second, 1)], 2)
    assert manabase.lands == (LandEntry("Test Barrens", None, 2),)
    assert manabase.sources == {W: 2, B: 2}


def test_a_splash_without_fixing_gets_three_basics() -> None:
    manabase = build_manabase(SPELLS, (W, B), R, [], 17)
    assert manabase.lands[0] == LandEntry("Mountain", R, 3)
    assert manabase.sources[R] == 3
    assert sum(entry.count for entry in manabase.lands) == 17
    assert list(manabase.sources) == [W, B, R]


def test_a_splash_with_a_fixing_land_gets_only_the_basics_it_still_needs() -> None:
    manabase = build_manabase(SPELLS, (W, B), R, [(TRI_LAND, 1)], 17)
    assert LandEntry("Mountain", R, 2) in manabase.lands
    assert manabase.sources[R] == 3


def test_a_splash_already_at_its_sources_still_gets_one_basic() -> None:
    manabase = build_manabase(SPELLS, (W, B), R, [(TRI_LAND, 3)], 17)
    assert LandEntry("Mountain", R, 1) in manabase.lands
    assert manabase.sources[R] == 4


def test_the_splash_minimum_is_configurable() -> None:
    manabase = build_manabase(SPELLS, (W, B), R, [], 17, splash_sources=4)
    assert manabase.sources[R] == 4


def test_a_splash_with_no_slots_left_gets_no_basic() -> None:
    white_red = land("White Red", ("W", "R"))
    manabase = build_manabase(SPELLS, (W, B), R, [(white_red, 2)], 2)
    assert manabase.lands == (LandEntry("White Red", None, 2),)
    assert manabase.sources == {W: 2, B: 0, R: 2}


@pytest.mark.parametrize("total", [16, 17])
def test_every_land_slot_is_filled(total: int) -> None:
    manabase = build_manabase(SPELLS, (W, B), G, [(BARRENS, 1), (GREAT_HALL, 1)], total)
    assert sum(entry.count for entry in manabase.lands) == total
