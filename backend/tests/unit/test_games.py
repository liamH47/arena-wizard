from __future__ import annotations

import datetime as dt
import io
from collections.abc import Iterator

import pytest

from arena_wizard.domain.stats import CardCounts, PairCounts
from arena_wizard.etl.games import (
    FileLayout,
    Game,
    count_daily,
    parse_layout,
    read_games,
    snapshot,
)
from arena_wizard.eval.build_set import collect_pools
from arena_wizard.eval.records import BuildRecord
from tests.seventeenlands_fixture import DAY1, DAY2, NAMES, ROWS, header, row


def _games() -> tuple[FileLayout, Iterator[Game]]:
    return read_games(io.StringIO("﻿" + "\n".join([header(), *ROWS, ""])))


def test_the_layout_finds_every_family_and_quoted_names() -> None:
    layout, _ = _games()
    assert layout.names == tuple(NAMES)
    assert set(layout.columns) == {"deck_", "sideboard_", "opening_hand_", "drawn_", "tutored_"}


def test_a_row_keeps_only_non_zero_cells() -> None:
    _, games = _games()
    first = next(games)
    assert first.deck == {0: 1, 1: 2, 2: 17}
    assert first.seen == frozenset({0, 2})
    assert first.won and first.win_rate_bucket == 0.6 and first.games_bucket == 50


def test_daily_counts_match_the_hand_computed_values() -> None:
    layout, games = _games()
    daily = count_daily(layout.names, games)
    assert daily.cards[DAY1] == {
        "Alpha": CardCounts(1, 1, 0, 0, 2, 1),
        "Beta, the Second": CardCounts(1, 0, 1, 1, 2, 1),
        "Plains": CardCounts(1, 1, 1, 0, 2, 1),
    }
    assert daily.cards[DAY2] == {
        "Alpha": CardCounts(1, 1, 0, 0, 1, 1),
        "Beta, the Second": CardCounts(1, 0, 0, 0, 1, 0),
        "Plains": CardCounts(0, 0, 2, 1, 2, 1),
    }
    assert daily.pairs[DAY1] == {"WB": PairCounts(2, 1)}
    assert daily.pairs[DAY2] == {"UR": PairCounts(1, 1), "WR": PairCounts(1, 0)}


def test_a_snapshot_sums_its_window_and_records_it() -> None:
    layout, games = _games()
    daily = count_daily(layout.names, games)
    whole = snapshot(daily, "SOS", "test", "abc")
    assert whole.cards["Alpha"] == CardCounts(2, 2, 0, 0, 3, 2)
    assert whole.source.games == 4
    assert (whole.source.first_day, whole.source.last_day) == (DAY1, DAY2)
    first_day = snapshot(daily, "SOS", "test", None, last=DAY1)
    assert first_day.cards["Alpha"].games_gih == 1 and first_day.source.games == 2
    empty = snapshot(daily, "SOS", "test", None, first=dt.date(2030, 1, 1))
    assert empty.cards == {} and empty.source.first_day is None


def test_pools_group_builds_and_drop_basics() -> None:
    layout, games = _games()
    pools = collect_pools(layout.names, games)
    d1 = pools["d1"]
    assert d1.pool == {"Alpha": 1, "Beta, the Second": 2}
    assert d1.first_day == DAY1
    assert d1.builds == (
        BuildRecord(0, "WB", "", {"Alpha": 1, "Beta, the Second": 2, "Plains": 17}, 2, 1),
        BuildRecord(1, "WR", "", {"Beta, the Second": 1, "Plains": 16}, 1, 0),
    )
    assert (d1.games, d1.wins, d1.first_build.main_colors) == (3, 1, "WB")
    assert pools["d2"].pool == {"Alpha": 1, "Beta, the Second": 1}


def test_a_later_row_with_an_earlier_date_moves_the_first_day_back() -> None:
    layout, _ = _games()
    late_first = [ROWS[2], row("d2", 0, "2026-04-20", "UR", False, (1, 0, 17))]
    _, games = read_games(io.StringIO("\n".join([header(), *late_first])))
    assert collect_pools(layout.names, games)["d2"].first_day == dt.date(2026, 4, 20)


def test_a_header_with_mismatched_families_is_rejected() -> None:
    with pytest.raises(ValueError, match="sideboard_"):
        parse_layout(["draft_id", "deck_A", "sideboard_B"])


def test_a_header_without_the_metadata_is_rejected() -> None:
    families = ["deck_A", "sideboard_A", "opening_hand_A", "drawn_A", "tutored_A"]
    with pytest.raises(ValueError, match="build_index"):
        parse_layout(["draft_id", "game_time", "main_colors", "won", *families])


def test_blank_optional_fields_become_none() -> None:
    blank = row("d9", 0, "2026-04-21", "WB", True, (1, 0, 17)).replace(",0.6,50,", ",,,")
    _, games = read_games(io.StringIO(f"{header()}\n{blank}\n\n"))
    game = next(games)
    assert game.win_rate_bucket is None and game.games_bucket is None


@pytest.mark.parametrize("won", ["true", "1", ""])
def test_a_won_cell_other_than_true_or_false_is_rejected(won: str) -> None:
    changed = row("d9", 0, "2026-04-21", "WB", True, (1, 0, 17)).replace(",True,", f",{won},")
    _, games = read_games(io.StringIO("\n".join([header(), changed, ""])))
    with pytest.raises(ValueError, match="True or False"):
        next(games)
