"""Matching pasted names to a set's cards, however people type them (decision 0007)."""

from __future__ import annotations

import dataclasses

import pytest

from arena_wizard.domain.cards import Card, CardFace
from arena_wizard.pastes.names import fold, name_index, resolve
from tests.unit.test_lands import card


def _face(name: str) -> CardFace:
    return CardFace(name, "", "Instant", "", None, None)


def _two_faced(front: str, back: str) -> Card:
    return dataclasses.replace(
        card(front), name=f"{front} // {back}", faces=(_face(front), _face(back))
    )


PREPARE = _two_faced("Semester Foreseer", "Peer Review")
PLAIN = [card("Jace's Machinations"), card("Curse-Marred Demon"), card("Consider")]


def test_folding_normalizes_case_apostrophes_dashes_and_spaces() -> None:
    assert fold("  JACE’S   Machinations ") == "jace's machinations"
    assert fold("Curse–Marred Demon") == fold("Curse−Marred Demon") == "curse-marred demon"
    assert fold("Ａ") == "a"


@pytest.mark.parametrize(
    ("typed", "front"),
    [
        ("Jace’s Machinations", "Jace's Machinations"),
        ("jace's machinations", "Jace's Machinations"),
        ("Curse—Marred  Demon", "Curse-Marred Demon"),
        ("Semester Foreseer // Peer Review", "Semester Foreseer"),
        ("Peer Review", "Semester Foreseer"),
        ("semester foreseer", "Semester Foreseer"),
    ],
)
def test_every_spelling_resolves_to_the_front_face_name(typed: str, front: str) -> None:
    assert resolve(typed, name_index([PREPARE, *PLAIN])) == front


def test_a_name_from_another_set_resolves_to_nothing() -> None:
    assert resolve("Lightning Bolt", name_index(PLAIN)) is None


def test_a_generator_of_cards_is_indexed_completely() -> None:
    index = name_index(c for c in [PREPARE, *PLAIN])
    assert resolve("Peer Review", index) == "Semester Foreseer"
    assert resolve("Consider", index) == "Consider"


def test_a_front_name_wins_over_another_cards_face_with_the_same_spelling() -> None:
    adventure = _two_faced("Tall Giant", "Consider")
    for order in ([adventure, *PLAIN], [*PLAIN, adventure]):
        assert resolve("Consider", name_index(order)) == "Consider"
