"""Read 17Lands game files into sparse game records and daily counts.

Each row of a game file is one game: metadata columns, then five columns per card (in the
deck, in the sideboard, in the opening hand, drawn, tutored). A row averages about 86
non-zero cells of about 1,730, so a game keeps only the non-zero ones. Everything here is
pure over already-decoded text; `etl/game_cache.py` does the downloading and caching.
"""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from arena_wizard.domain.stats import CardCounts, PairCounts, Snapshot, SourceRef

FAMILIES = ("deck_", "sideboard_", "opening_hand_", "drawn_", "tutored_")
COUNTS_VERSION = 1
"""Bump whenever `count_daily` changes what it counts, so cached counts are recounted."""


@dataclass(frozen=True, slots=True)
class FileLayout:
    """Where each piece of a row lives, derived from the header."""

    names: tuple[str, ...]
    meta: Mapping[str, int]
    columns: Mapping[str, tuple[int, ...]]


@dataclass(frozen=True, slots=True)
class Game:
    """One game, with card positions (indexes into `FileLayout.names`) for each family."""

    draft_id: str
    build_index: int
    day: dt.date
    main_colors: str
    splash_colors: str
    won: bool
    win_rate_bucket: float | None
    games_bucket: int | None
    deck: Mapping[int, int]
    sideboard: Mapping[int, int]
    seen: frozenset[int]
    tutored: frozenset[int]


def parse_layout(header: list[str]) -> FileLayout:
    """Map a header row to column positions. Pure.

    Raises:
        ValueError: The header lacks the metadata columns or the card families disagree.
    """
    names = tuple(h.removeprefix("deck_") for h in header if h.startswith("deck_"))
    columns = {}
    for family in FAMILIES:
        positions = {
            h.removeprefix(family): i for i, h in enumerate(header) if h.startswith(family)
        }
        if set(positions) != set(names):
            raise ValueError(f"the {family} columns do not match the deck_ columns")
        columns[family] = tuple(positions[name] for name in names)
    meta = {h: i for i, h in enumerate(header) if not h.startswith(FAMILIES)}
    missing = {"draft_id", "build_index", "game_time", "main_colors", "won"} - set(meta)
    if missing:
        raise ValueError(f"game file header lacks {sorted(missing)}")
    return FileLayout(names=names, meta=meta, columns=columns)


def _nonzero(row: list[str], positions: tuple[int, ...]) -> dict[int, int]:
    """Card index to count for the non-zero cells among `positions`."""
    return {
        card: int(row[column])
        for card, column in enumerate(positions)
        if row[column] not in ("0", "")
    }


def _won(text: str) -> bool:
    """17Lands writes the literal True or False; anything else means the format changed."""
    if text not in ("True", "False"):
        raise ValueError(f"the won column must be True or False, got {text!r}")
    return text == "True"


def _optional_float(text: str) -> float | None:
    return float(text) if text else None


def _optional_int(text: str) -> int | None:
    return int(text) if text else None


def parse_game(row: list[str], layout: FileLayout) -> Game:
    """Parse one data row. Pure."""
    meta = layout.meta

    def field(name: str) -> str:
        return row[meta[name]] if name in meta else ""

    seen = _nonzero(row, layout.columns["opening_hand_"]) | _nonzero(row, layout.columns["drawn_"])
    return Game(
        draft_id=field("draft_id"),
        build_index=int(field("build_index") or 0),
        day=dt.date.fromisoformat(field("game_time")[:10]),
        main_colors=field("main_colors"),
        splash_colors=field("splash_colors"),
        won=_won(field("won")),
        win_rate_bucket=_optional_float(field("user_game_win_rate_bucket")),
        games_bucket=_optional_int(field("user_n_games_bucket")),
        deck=_nonzero(row, layout.columns["deck_"]),
        sideboard=_nonzero(row, layout.columns["sideboard_"]),
        seen=frozenset(seen),
        tutored=frozenset(_nonzero(row, layout.columns["tutored_"])),
    )


def read_games(lines: Iterable[str]) -> tuple[FileLayout, Iterator[Game]]:
    """Parse decoded CSV lines into a layout and a lazy stream of games. Pure.

    Uses a real CSV parser: card names containing commas are quoted in the header.
    """
    reader = csv.reader(lines)
    header = next(reader)
    header[0] = header[0].removeprefix("﻿")
    layout = parse_layout(header)
    return layout, (parse_game(row, layout) for row in reader if row)


@dataclass(frozen=True, slots=True)
class DailyCounts:
    """Card and pair counts per day of play (UTC game date)."""

    names: tuple[str, ...]
    cards: Mapping[dt.date, Mapping[str, CardCounts]]
    pairs: Mapping[dt.date, Mapping[str, PairCounts]]


def count_daily(names: tuple[str, ...], games: Iterable[Game]) -> DailyCounts:
    """Accumulate per-day counts from games. Pure.

    A card counts once per game however many copies it has: in hand when in the opening
    hand or drawn, not seen when in the deck but neither seen nor tutored.
    """
    cards: dict[dt.date, dict[int, list[int]]] = {}
    pairs: dict[dt.date, dict[str, list[int]]] = {}
    for game in games:
        day_cards = cards.setdefault(game.day, {})
        win = int(game.won)
        for index in game.deck:
            c = day_cards.setdefault(index, [0, 0, 0, 0, 0, 0])
            c[4] += 1
            c[5] += win
            if index in game.seen:
                c[0] += 1
                c[1] += win
            elif index not in game.tutored:
                c[2] += 1
                c[3] += win
        p = pairs.setdefault(game.day, {}).setdefault(game.main_colors, [0, 0])
        p[0] += 1
        p[1] += win
    return DailyCounts(
        names=names,
        cards={
            day: {names[i]: CardCounts(*c) for i, c in sorted(by_card.items())}
            for day, by_card in sorted(cards.items())
        },
        pairs={
            day: {code: PairCounts(g, w) for code, (g, w) in sorted(by_pair.items())}
            for day, by_pair in sorted(pairs.items())
        },
    )


def snapshot(
    daily: DailyCounts,
    set_code: str,
    label: str,
    sha256: str | None,
    first: dt.date | None = None,
    last: dt.date | None = None,
) -> Snapshot:
    """Sum the days in [first, last] (open ends take everything) into a Snapshot. Pure."""
    days = [d for d in daily.cards if (first is None or d >= first) and (last is None or d <= last)]
    cards: dict[str, CardCounts] = {}
    pairs: dict[str, PairCounts] = {}
    for day in days:
        for name, card in daily.cards[day].items():
            cards[name] = cards.get(name, CardCounts()) + card
        for code, pair in daily.pairs.get(day, {}).items():
            pairs[code] = pairs.get(code, PairCounts()) + pair
    games = sum(p.games for p in pairs.values())
    source = SourceRef(
        label=label,
        first_day=min(days) if days else None,
        last_day=max(days) if days else None,
        content_sha256=sha256,
        games=games,
    )
    return Snapshot(set_code=set_code, source=source, cards=cards, pairs=pairs)
