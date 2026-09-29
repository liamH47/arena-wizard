"""Download a 17Lands game file once and keep its daily counts in a local cache.

Developer and CLI use only: the web app gets the same counts through its database in a
later milestone. The cache lives outside the repository (default `~/.cache/arena-wizard`,
or `ARENA_WIZARD_CACHE_DIR`), because the counts are derived from 17Lands data and the
full file is several megabytes.

A download is skipped only when the cached file is still on disk, its hash matches the
cached counts, and the server's ETag is unchanged. Counts written by older counting rules
(`COUNTS_VERSION`) are recounted from the cached file without downloading it again.
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from arena_wizard.domain.sets import EventType
from arena_wizard.domain.stats import CardCounts, PairCounts
from arena_wizard.etl.cache_paths import cache_dir, counts_path, file_path
from arena_wizard.etl.games import COUNTS_VERSION, DailyCounts, count_daily, read_games
from arena_wizard.fileio import atomic_write_bytes, atomic_write_text
from arena_wizard.sources.http import SourceContext, SourceError
from arena_wizard.sources.seventeenlands_files import public_file_url

__all__ = [
    "CACHE_FORMAT",
    "CachedCounts",
    "LoadStatus",
    "cache_dir",
    "count_bytes",
    "counts_from_json",
    "counts_path",
    "counts_to_json",
    "download",
    "file_path",
    "load_file",
    "read_cached",
]

CACHE_FORMAT = 2
LoadStatus = Literal["downloaded", "recounted", "unchanged"]


@dataclass(frozen=True, slots=True)
class CachedCounts:
    """Daily counts plus where they came from and which counting rules produced them."""

    set_code: str
    event_type: EventType
    url: str
    sha256: str
    etag: str | None
    counts_version: int
    daily: DailyCounts


def count_bytes(data: bytes) -> DailyCounts:
    """Decompress a gzipped game file and count it. Pure."""
    layout, games = read_games(io.StringIO(gzip.decompress(data).decode("utf-8"), newline=""))
    return count_daily(layout.names, games)


def counts_to_json(cached: CachedCounts) -> str:
    """Serialize deterministically. Pure."""
    days = {
        day.isoformat(): {
            "cards": {
                name: [
                    c.games_gih,
                    c.wins_gih,
                    c.games_gns,
                    c.wins_gns,
                    c.games_played,
                    c.wins_played,
                ]
                for name, c in cached.daily.cards[day].items()
            },
            "pairs": {
                code: [p.games, p.wins] for code, p in cached.daily.pairs.get(day, {}).items()
            },
        }
        for day in cached.daily.cards
    }
    document = {
        "format_version": CACHE_FORMAT,
        "counts_version": cached.counts_version,
        "set_code": cached.set_code,
        "event_type": cached.event_type.value,
        "url": cached.url,
        "sha256": cached.sha256,
        "etag": cached.etag,
        "names": list(cached.daily.names),
        "days": days,
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def counts_from_json(text: str) -> CachedCounts | None:
    """Parse `counts_to_json` output; None when it was written by an incompatible version."""
    document: dict[str, Any] = json.loads(text)
    if document.get("format_version") != CACHE_FORMAT:
        return None
    cards: dict[dt.date, dict[str, CardCounts]] = {}
    pairs: dict[dt.date, dict[str, PairCounts]] = {}
    for day_text, day in document["days"].items():
        day_date = dt.date.fromisoformat(day_text)
        cards[day_date] = {name: CardCounts(*v) for name, v in day["cards"].items()}
        pairs[day_date] = {code: PairCounts(*v) for code, v in day["pairs"].items()}
    return CachedCounts(
        set_code=document["set_code"],
        event_type=EventType(document["event_type"]),
        url=document["url"],
        sha256=document["sha256"],
        etag=document["etag"],
        counts_version=document["counts_version"],
        daily=DailyCounts(names=tuple(document["names"]), cards=cards, pairs=pairs),
    )


def download(ctx: SourceContext, url: str) -> tuple[bytes, str | None]:
    """Fetch a whole file and return its bytes and ETag.

    Raises:
        SourceError: The request did not succeed.
    """
    ctx.throttle.wait("17lands", ctx.sleep, ctx.monotonic)
    buffer = io.BytesIO()
    with ctx.client.stream("GET", url) as response:
        if response.status_code != 200:
            raise SourceError(f"{url} returned {response.status_code}")
        for chunk in response.iter_raw():
            buffer.write(chunk)
        etag = response.headers.get("ETag")
    return buffer.getvalue(), etag


def _cached_file(path: Path, sha256: str) -> bytes | None:
    """The cached file's bytes when it exists and still has the expected hash."""
    if not path.is_file():
        return None
    data = path.read_bytes()
    return data if hashlib.sha256(data).hexdigest() == sha256 else None


def load_file(
    ctx: SourceContext, set_code: str, event_type: EventType, root: Path | None = None
) -> tuple[CachedCounts, LoadStatus]:
    """Make sure the local cache holds current counts for one public game file.

    Args:
        ctx: The injected context.
        set_code: The 17Lands expansion code.
        event_type: Which file.
        root: The cache directory; defaults to `cache_dir()`.

    Returns:
        The counts, and whether the file was downloaded, only recounted, or unchanged.

    Raises:
        SourceError: The file does not exist or a request failed.
    """
    base = root or cache_dir()
    url = public_file_url(set_code, event_type)
    counts_file = counts_path(base, set_code, event_type)
    gz = file_path(base, set_code, event_type)
    cached = read_cached(set_code, event_type, base)
    ctx.throttle.wait("17lands", ctx.sleep, ctx.monotonic)
    head = ctx.client.head(url)
    if head.status_code != 200:
        raise SourceError(f"{url} returned {head.status_code}")
    etag = head.headers.get("ETag")
    local = _cached_file(gz, cached.sha256) if cached is not None else None
    if cached is not None and local is not None and etag is not None and cached.etag == etag:
        if cached.counts_version == COUNTS_VERSION:
            return cached, "unchanged"
        data = local
        status: LoadStatus = "recounted"
    else:
        data, etag = download(ctx, url)
        atomic_write_bytes(gz, data)
        status = "downloaded"
    result = CachedCounts(
        set_code=set_code,
        event_type=event_type,
        url=url,
        sha256=hashlib.sha256(data).hexdigest(),
        etag=etag,
        counts_version=COUNTS_VERSION,
        daily=count_bytes(data),
    )
    atomic_write_text(counts_file, counts_to_json(result))
    return result, status


def read_cached(
    set_code: str, event_type: EventType, root: Path | None = None
) -> CachedCounts | None:
    """Cached counts for a file, or None when missing or written by an incompatible version."""
    path = counts_path(root or cache_dir(), set_code, event_type)
    return counts_from_json(path.read_text(encoding="utf-8")) if path.is_file() else None
