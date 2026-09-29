"""Derive the fixed evaluation set from a 17Lands Sealed game file.

`split_day` is the day by which 60% of the file's games had been played. The sample is
pools whose first game came after it, stratified by the colors of the player's first
deck in proportion to the population and chosen within each stratum by a hash of the
draft id, so anyone can reproduce it. Statistics come only from games on or before the
split day, so the engine is scored out of sample. The file has no user id, so a player
can appear on both sides of the split; that cannot be measured and the report says so.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from fractions import Fraction
from itertools import accumulate

from arena_wizard.etl.games import Game
from arena_wizard.eval.records import BuildRecord, PoolRecord

BASICS = frozenset({"Plains", "Island", "Swamp", "Mountain", "Forest"})
SPLIT_SHARE = Fraction(3, 5)


@dataclass(slots=True)
class _Build:
    """A build being accumulated from its games."""

    main_colors: str
    splash_colors: str
    deck: dict[str, int]
    games: int = 0
    wins: int = 0


@dataclass(slots=True)
class _Pool:
    """A pool being accumulated from its games."""

    first_day: dt.date
    pool: dict[str, int]
    builds: dict[int, _Build]
    win_rate_bucket: float | None
    games_bucket: int | None


def collect_pools(names: tuple[str, ...], games: Iterable[Game]) -> dict[str, PoolRecord]:
    """Group games into pool records. Pure.

    The pool is the same in every row of a draft (measured on every SOS and HOB pool), so
    it is taken from the first row seen; basics are dropped because Arena supplies them.
    """
    pools: dict[str, _Pool] = {}
    for game in games:
        pool = pools.get(game.draft_id)
        if pool is None:
            cards: dict[str, int] = {}
            for index, count in (*game.deck.items(), *game.sideboard.items()):
                name = names[index]
                if name not in BASICS:
                    cards[name] = cards.get(name, 0) + count
            pool = _Pool(game.day, cards, {}, game.win_rate_bucket, game.games_bucket)
            pools[game.draft_id] = pool
        pool.first_day = min(pool.first_day, game.day)
        build = pool.builds.get(game.build_index)
        if build is None:
            deck = {names[i]: n for i, n in game.deck.items()}
            build = _Build(game.main_colors, game.splash_colors, deck)
            pool.builds[game.build_index] = build
        build.games += 1
        build.wins += int(game.won)
    return {
        draft_id: PoolRecord(
            draft_id=draft_id,
            first_day=p.first_day,
            pool=p.pool,
            builds=tuple(
                BuildRecord(i, b.main_colors, b.splash_colors, b.deck, b.games, b.wins)
                for i, b in sorted(p.builds.items())
            ),
            win_rate_bucket=p.win_rate_bucket,
            games_bucket=p.games_bucket,
        )
        for draft_id, p in pools.items()
    }


def choose_split_day(
    games_per_day: Mapping[dt.date, int], share: Fraction = SPLIT_SHARE
) -> dt.date:
    """The first day by which `share` of all games had been played. Pure.

    Raises:
        ValueError: There are no games.
    """
    total = sum(games_per_day.values())
    if total == 0:
        raise ValueError("no games to split")
    days = sorted(games_per_day)
    running = accumulate(games_per_day[day] for day in days)
    # Integer arithmetic: in floating point 0.6 * 100 is 60.00000000000001.
    return next(
        day
        for day, games in zip(days, running, strict=True)
        if games * share.denominator >= total * share.numerator
    )


def _order_key(draft_id: str) -> str:
    """A stable pseudo-random order that anyone can reproduce."""
    return hashlib.sha256(draft_id.encode("utf-8")).hexdigest()


def select_sample(
    records: Mapping[str, PoolRecord], split_day: dt.date, size: int
) -> tuple[PoolRecord, ...]:
    """Pick the stratified, reproducible sample of pools that started after the split. Pure.

    Args:
        records: Every pool.
        split_day: Pools whose first game is on or before this day are excluded.
        size: How many pools to take (fewer if fewer qualify).

    Returns:
        The sample, ordered by stratum then hash.
    """
    eligible = [r for r in records.values() if r.first_day > split_day]
    strata: dict[str, list[PoolRecord]] = {}
    for record in eligible:
        strata.setdefault(record.first_build.main_colors, []).append(record)
    target = min(size, len(eligible))
    exact = {k: target * len(v) / len(eligible) for k, v in strata.items()} if eligible else {}
    quota = {k: int(v) for k, v in exact.items()}
    by_remainder = sorted(exact, key=lambda k: (-(exact[k] - quota[k]), k))
    for key in by_remainder[: target - sum(quota.values())]:
        quota[key] += 1
    sample: list[PoolRecord] = []
    for key in sorted(strata):
        members = sorted(strata[key], key=lambda r: _order_key(r.draft_id))
        sample += members[: quota[key]]
    return tuple(sample)
