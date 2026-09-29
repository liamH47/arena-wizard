"""What a card does in a limited deck, read from its type line and rules text.

The patterns were written against the SOS and HOB card text and are golden-tested on
hand-labelled real cards (`tests/golden/test_roles.py`). They are heuristics: a miss
costs a removal or creature count one card, and the card's win rate still carries most of
its value.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import cache

from arena_wizard.domain.cards import Card
from arena_wizard.engine.mana import dependable_colors


class Role(StrEnum):
    """A job a card does in a deck."""

    CREATURE = "creature"
    LAND = "land"
    REMOVAL = "removal"
    CARD_ADVANTAGE = "card_advantage"
    FIXING = "fixing"
    EVASIVE = "evasive"
    COMBAT_TRICK = "combat_trick"


_REMOVAL = re.compile(
    "|".join(
        [
            r"(?:destroy|exile) target (?:\w+ ){0,3}?(?:creature|nonland permanent|permanent)\b",
            r"deals? (?:\d+|x|that much damage|damage equal to [^.]*?) (?:damage )?to "
            r"(?:any target|each creature|target (?:\w+ ){0,3}?creature)",
            r"gets? -[2-9]/-[2-9]",
            r"-x/-x",
            r"\bfights? (?:target|up to one target|another target)",
            r"enchanted creature can't attack or block",
            r"doesn't untap during its controller's untap step",
            r"sacrifices? (?:a|an) (?:creature|attacking creature|nonland permanent)",
        ]
    )
)
_CARD_ADVANTAGE = re.compile(
    # Drawing one card replaces itself; card advantage means more than that.
    r"draws? (?:two|three|four|five|x|[2-9]|2ˣ) (?:additional )?cards"
    r"|put (?:two|three) of them into your hand"
    r"|return target [^.]*? card from your graveyard to your hand"
)
_FIXING = re.compile(
    r"add one mana of any color|search your library for (?:a|up to two) basic land"
    r"|create (?:a|two) treasure"
)
_EVASION = re.compile(r"\b(?:flying|menace)\b|can't be blocked")
_PUMP = re.compile(r"target creature (?:you control )?gets \+\d+/\+\d+")


def _front_type(card: Card) -> str:
    """The front face's type line (the whole type line for one-face cards)."""
    return card.faces[0].type_line if card.faces else card.type_line


@cache
def classify(card: Card) -> frozenset[Role]:
    """Return every role a card plays. Pure.

    Args:
        card: The card.

    Returns:
        Its roles; empty for a card that does none of the tracked jobs.
    """
    text = card.oracle_text.lower()
    front = _front_type(card)
    roles: set[Role] = set()
    if "Land" in front:
        roles.add(Role.LAND)
        if len(dependable_colors(card)) >= 2:
            roles.add(Role.FIXING)
        return frozenset(roles)
    if "Creature" in front:
        roles.add(Role.CREATURE)
        if _EVASION.search(text):
            roles.add(Role.EVASIVE)
    if _REMOVAL.search(text):
        roles.add(Role.REMOVAL)
    if _CARD_ADVANTAGE.search(text):
        roles.add(Role.CARD_ADVANTAGE)
    if _FIXING.search(text):
        roles.add(Role.FIXING)
    if "Instant" in front and _PUMP.search(text):
        roles.add(Role.COMBAT_TRICK)
    return frozenset(roles)
