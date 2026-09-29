"""Turn parsed export lines into a Pool of known cards.

Resolution order: the exact printing (set code and collector number) in the set's table;
then the card's name in the set's table (an alternate printing); then the name in any
other packaged table (a card from another set); otherwise an unknown name with up to three
suggestions. Copies of the same card under different printings merge into one entry.
Nothing here raises on bad input: every problem becomes a warning on the pool.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from arena_wizard.catalog import CardTable, collector_sort_key
from arena_wizard.domain.cards import Card
from arena_wizard.domain.pool import ParsedLine, ParseWarning, Pool, PoolEntry, WarningKind
from arena_wizard.domain.sets import Format, SetConfig


@dataclass(frozen=True, slots=True)
class CardIndex:
    """Lookups over one or more card tables."""

    by_print: Mapping[tuple[str, str], Card]
    by_name: Mapping[str, Card]


def build_index(tables: Iterable[CardTable], home_set: str | None = None) -> CardIndex:
    """Index cards by printing and by name. Pure.

    A name maps to one canonical printing: the home set's own printing if it has one, then
    the lowest collector number.

    Args:
        tables: The tables to index.
        home_set: The set whose printings win name lookups.

    Returns:
        The index; both the front-face name and the full name map to the card.
    """
    by_print: dict[tuple[str, str], Card] = {}
    candidates: dict[str, list[Card]] = {}
    for table in tables:
        for card in table.cards:
            by_print[(card.set_code, card.collector_number)] = card
            for name in {card.front_name, card.name}:
                candidates.setdefault(name, []).append(card)
    by_name = {
        name: min(
            cards,
            key=lambda c: (
                c.set_code != home_set,
                c.set_code,
                collector_sort_key(c.collector_number),
            ),
        )
        for name, cards in candidates.items()
    }
    return CardIndex(by_print=by_print, by_name=by_name)


def _suggest(name: str, index: CardIndex) -> tuple[str, ...]:
    """Up to three close names from the index."""
    return tuple(difflib.get_close_matches(name, list(index.by_name), n=3, cutoff=0.8))


def resolve_card(
    line: ParsedLine, home: CardIndex, others: CardIndex
) -> tuple[Card | None, ParseWarning | None]:
    """Resolve one line. Pure.

    Args:
        line: The parsed line.
        home: The pool's own set.
        others: Every other packaged set, for cards that are not from this set.

    Returns:
        The card (None when unknown) and a warning when the player should look.
    """
    exact = home.by_print.get((line.set_code, line.collector_number))
    if exact is not None:
        return exact, None
    named = home.by_name.get(line.name)
    if named is not None:
        return named, ParseWarning(
            kind=WarningKind.ALTERNATE_PRINTING,
            message=f"{line.name} ({line.set_code}) {line.collector_number} matched by name",
            line_no=line.line_no,
        )
    elsewhere = others.by_print.get((line.set_code, line.collector_number)) or others.by_name.get(
        line.name
    )
    if elsewhere is not None:
        return elsewhere, ParseWarning(
            kind=WarningKind.WRONG_SET,
            message=f"{line.name} is not from this set; it is included without set statistics",
            line_no=line.line_no,
        )
    return None, ParseWarning(
        kind=WarningKind.UNKNOWN_NAME,
        message=f"{line.name} is not a known card; it will be in no deck",
        line_no=line.line_no,
        raw=f"{line.count} {line.name} ({line.set_code}) {line.collector_number}",
        suggestions=_suggest(line.name, home),
    )


def _printing_order(card: Card, home: str) -> tuple[bool, str, tuple[int, str]]:
    """Which printing represents merged copies: the home set first, then the lowest number."""
    return (card.set_code != home, card.set_code, collector_sort_key(card.collector_number))


def resolve_pool(
    items: Iterable[ParsedLine | ParseWarning],
    config: SetConfig,
    home: CardIndex,
    others: CardIndex,
    fmt: Format = Format.BO1_SEALED,
) -> Pool:
    """Resolve parsed export items into a Pool. Pure.

    Args:
        items: The parser's output, lines and warnings in order.
        config: The pool's set.
        home: The set's card index.
        others: Every other packaged set.
        fmt: The format the pool is for.

    Returns:
        The pool, with every warning from parsing and resolution in line order, plus an
        advisory pool-size warning when the non-basic count is outside the set's range.
    """
    warnings: list[ParseWarning] = []
    counts: dict[str, int] = {}
    cards: dict[str, Card] = {}
    for item in items:
        if isinstance(item, ParseWarning):
            warnings.append(item)
            continue
        card, warning = resolve_card(item, home, others)
        if warning is not None:
            warnings.append(warning)
        if card is not None:
            # Copies under different printings merge under one printing chosen by the
            # card, never by line order: the home set's, then the lowest collector number.
            kept = cards.get(card.oracle_id)
            if kept is None or _printing_order(card, config.code) < _printing_order(
                kept, config.code
            ):
                cards[card.oracle_id] = card
            counts[card.oracle_id] = counts.get(card.oracle_id, 0) + item.count
    entries = sorted(
        (PoolEntry(cards[key], counts[key]) for key in cards),
        key=lambda e: (e.card.front_name, collector_sort_key(e.card.collector_number)),
    )
    spells = tuple(e for e in entries if not e.card.is_basic)
    basics = tuple(e for e in entries if e.card.is_basic)
    nonbasic = sum(e.count for e in spells)
    low, high = config.nonbasic_pool_range
    if not low <= nonbasic <= high:
        warnings.append(
            ParseWarning(
                kind=WarningKind.POOL_SIZE,
                message=f"{nonbasic} non-basic cards; {config.code} pools run {low} to {high}",
            )
        )
    return Pool(
        set_code=config.code, format=fmt, entries=spells, basics=basics, warnings=tuple(warnings)
    )
