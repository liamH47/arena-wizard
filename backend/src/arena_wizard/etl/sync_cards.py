"""Build a set's card table from Scryfall, checked against the 17Lands game-file header.

`fetch_card_sources` does the I/O; `compute_card_table` is pure. A card that appears in a
17Lands header but in none of the set's Scryfall queries (a bonus-sheet or Special Guests
printing, for example) is looked up by exact name and all of its Arena printings are
added, so the resolver can match any collector number an export line carries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from arena_wizard.catalog import CardTable, HeaderInfo
from arena_wizard.domain.sets import EventType, SetConfig
from arena_wizard.sources import scryfall, seventeenlands_files
from arena_wizard.sources.http import SourceContext

HEADER_EVENT_TYPES: tuple[EventType, ...] = (EventType.SEALED, EventType.PREMIER_DRAFT)
"""Which 17Lands files to take the header from, in order of preference."""


@dataclass(frozen=True, slots=True)
class CardSources:
    """The raw material for one set's card table."""

    raw_cards: tuple[Mapping[str, Any], ...]
    header: HeaderInfo | None


def compute_card_table(config: SetConfig, sources: CardSources) -> CardTable:
    """Assemble a card table from raw Scryfall cards. Pure.

    Args:
        config: The set's configuration.
        sources: Raw cards (duplicates allowed) and the header, if one exists.

    Returns:
        The table, one card per Scryfall printing.
    """
    by_id: dict[str, Mapping[str, Any]] = {}
    for raw in sources.raw_cards:
        by_id.setdefault(raw["id"], raw)
    return CardTable(
        set_code=config.code,
        scryfall_queries=config.scryfall_queries,
        header=sources.header,
        cards=tuple(scryfall.compute_card(raw) for raw in by_id.values()),
    )


def fetch_header(ctx: SourceContext, config: SetConfig) -> HeaderInfo | None:
    """Return the first available 17Lands header for the set, or None before any exists."""
    for event_type in HEADER_EVENT_TYPES:
        url = seventeenlands_files.public_file_url(config.seventeenlands_expansion, event_type)
        names = seventeenlands_files.fetch_card_names(ctx, url)
        if names is not None:
            return HeaderInfo(event_type=event_type, names=names)
    return None


def _missing_names(raw_cards: Iterable[Mapping[str, Any]], names: Iterable[str]) -> list[str]:
    """Return header names that match no raw card's full or front-face name."""
    known: set[str] = set()
    for raw in raw_cards:
        known.add(raw["name"])
        faces = raw.get("card_faces") or []
        if faces:
            known.add(faces[0]["name"])
    return [name for name in names if name not in known]


def fetch_card_sources(ctx: SourceContext, config: SetConfig) -> CardSources:
    """Fetch every Arena printing the set's pools can contain.

    Args:
        ctx: The injected context.
        config: The set's configuration.

    Returns:
        The raw cards from each query plus those found by header name, and the header.
    """
    raw_cards: list[Mapping[str, Any]] = []
    for query in config.scryfall_queries:
        raw_cards.extend(scryfall.fetch_search(ctx, query))
    header = fetch_header(ctx, config)
    if header is not None:
        for name in _missing_names(raw_cards, header.names):
            oracle_id = scryfall.fetch_oracle_id(ctx, name)
            if oracle_id is not None:
                raw_cards.extend(scryfall.fetch_search(ctx, f"oracleid:{oracle_id}"))
    return CardSources(raw_cards=tuple(raw_cards), header=header)
