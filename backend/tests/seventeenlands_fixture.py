"""A tiny synthetic 17Lands game file whose counts are worked out by hand in test_games."""

from __future__ import annotations

import datetime as dt
import gzip

NAMES = ["Alpha", "Beta, the Second", "Plains"]
META = "expansion,event_type,draft_id,build_index,game_time,main_colors,splash_colors,won"
META += ",user_game_win_rate_bucket,user_n_games_bucket"


def header() -> str:
    families = ["deck_", "sideboard_", "opening_hand_", "drawn_", "tutored_"]
    return META + "," + ",".join(f'"{f}{n}"' for f in families for n in NAMES)


def row(
    draft: str,
    build: int,
    day: str,
    colors: str,
    won: bool,
    deck: tuple[int, int, int],
    sideboard: tuple[int, int, int] = (0, 0, 0),
    hand: tuple[int, int, int] = (0, 0, 0),
    drawn: tuple[int, int, int] = (0, 0, 0),
    tutored: tuple[int, int, int] = (0, 0, 0),
) -> str:
    meta = f"SOS,Sealed,{draft},{build},{day} 10:00:00,{colors},,{won},0.6,50"
    cells = [*deck, *sideboard, *hand, *drawn, *tutored]
    return meta + "," + ",".join(str(c) for c in cells)


# Four games whose counts are worked out by hand in the tests below.
ROWS = [
    # d1 first build, day 1, won: Alpha in hand, Beta in deck unseen, a Plains drawn.
    row("d1", 0, "2026-04-21", "WB", True, (1, 2, 17), hand=(1, 0, 0), drawn=(0, 0, 3)),
    # d1 first build, day 1, lost: Beta in hand, Alpha tutored (neither in hand nor unseen).
    row("d1", 0, "2026-04-21", "WB", False, (1, 2, 17), hand=(0, 1, 0), tutored=(1, 0, 0)),
    # d2, day 2, won: Alpha drawn, Beta only in the sideboard.
    row("d2", 0, "2026-04-22", "UR", True, (1, 0, 17), sideboard=(0, 1, 0), drawn=(1, 0, 0)),
    # d1 rebuilt, day 2, lost: Beta drawn.
    row("d1", 1, "2026-04-22", "WR", False, (0, 1, 16), drawn=(0, 1, 0)),
]
DAY1, DAY2 = dt.date(2026, 4, 21), dt.date(2026, 4, 22)


def file_text() -> str:
    """The whole file, with a byte-order mark like 17Lands' CSV export."""
    return "\ufeff" + "\n".join([header(), *ROWS, ""])


def file_bytes() -> bytes:
    """The file gzipped, as 17Lands publishes it."""
    return gzip.compress(file_text().encode("utf-8"))
