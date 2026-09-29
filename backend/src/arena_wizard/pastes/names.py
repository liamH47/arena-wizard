"""Match pasted card names to a set's cards, forgiving how people type them. Pure.

17Lands writes front-face names. Hand-typed lists vary: case, curly apostrophes, en
dashes, double spaces, a full `A // B` name, or the back face alone. All of those resolve
to the 17Lands (front-face) name.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping

from arena_wizard.domain.cards import Card

_FOLD = str.maketrans({"’": "'", "‘": "'", "–": "-", "—": "-", "−": "-"})


def fold(name: str) -> str:
    """The comparison form of a name: NFKC, typographic marks folded, case-folded."""
    text = unicodedata.normalize("NFKC", name).translate(_FOLD).casefold()
    return " ".join(text.split())


def name_index(cards: Iterable[Card]) -> dict[str, str]:
    """Map every folded spelling (front, full, each face) to the front-face name."""
    cards = tuple(cards)
    index: dict[str, str] = {}
    for card in cards:
        spellings = [card.front_name, card.name, *(face.name for face in card.faces)]
        for spelling in spellings:
            index.setdefault(fold(spelling), card.front_name)
    # Front names win over a face that happens to share a folded spelling.
    for card in cards:
        index[fold(card.front_name)] = card.front_name
    return index


def resolve(name: str, index: Mapping[str, str]) -> str | None:
    """The front-face name for a pasted name, or None when it is not in the set."""
    return index.get(fold(name))
