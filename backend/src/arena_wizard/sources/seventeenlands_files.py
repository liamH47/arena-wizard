"""17Lands public game files: the primary source for sealed card statistics.

The files are CC BY 4.0 and hosted on S3. This module currently reads only the header
row, which names every card that appeared in the event: reading it decompresses the first
few kilobytes and closes the connection instead of downloading the whole file.
"""

from __future__ import annotations

import csv
import zlib
from collections.abc import Iterable

from arena_wizard.domain.sets import EventType
from arena_wizard.sources.http import SourceContext, SourceError

BASE_URL = "https://17lands-public.s3.amazonaws.com/analysis_data/game_data"
CARD_COLUMN_PREFIX = "deck_"
"""Every card gets one column per family; the deck_ family lists each card exactly once."""


def public_file_url(expansion: str, event_type: EventType) -> str:
    """Return the URL of a public game file.

    Args:
        expansion: The 17Lands expansion code, e.g. "SOS".
        event_type: The event type, e.g. EventType.SEALED.

    Returns:
        The HTTPS URL of the gzipped CSV.
    """
    return f"{BASE_URL}/game_data_public.{expansion}.{event_type.value}.csv.gz"


def first_line(chunks: Iterable[bytes]) -> str:
    """Decompress gzip chunks just far enough to return the first line. Pure.

    Args:
        chunks: The raw gzip bytes, in order.

    Returns:
        The first line without its line ending or a leading byte-order mark.

    Raises:
        SourceError: The stream is not valid gzip.
    """
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    buffered = bytearray()
    try:
        for chunk in chunks:
            buffered.extend(decompressor.decompress(chunk))
            if b"\n" in buffered:
                break
        else:
            buffered.extend(decompressor.flush())
    except zlib.error as exc:
        raise SourceError(f"not a gzip stream: {exc}") from exc
    line = bytes(buffered).split(b"\n", 1)[0].decode("utf-8")
    return line.removeprefix("﻿").rstrip("\r")


def parse_card_names(header_line: str) -> tuple[str, ...]:
    """Return the card names in a game-file header, in column order. Pure.

    Names containing commas are quoted in the file, so this uses a real CSV parser.

    Args:
        header_line: The first line of a game file.

    Returns:
        One name per card column, basics included.
    """
    columns = next(csv.reader([header_line]))
    return tuple(
        column.removeprefix(CARD_COLUMN_PREFIX)
        for column in columns
        if column.startswith(CARD_COLUMN_PREFIX)
    )


def fetch_card_names(ctx: SourceContext, url: str) -> tuple[str, ...] | None:
    """Read the card names from a public game file's header.

    Args:
        ctx: The injected context.
        url: The file URL from `public_file_url`.

    Returns:
        The names, or None when the file does not exist yet (S3 answers 403 or 404).

    Raises:
        SourceError: Any other status, or a body that is not gzip.
    """
    ctx.throttle.wait("17lands", ctx.sleep, ctx.monotonic)
    with ctx.client.stream("GET", url) as response:
        if response.status_code in (403, 404):
            return None
        if response.status_code != 200:
            raise SourceError(f"{url} returned {response.status_code}")
        # iter_raw, not iter_bytes: the file is gzip as stored, and must not be decoded
        # twice if S3 ever starts sending Content-Encoding.
        return parse_card_names(first_line(response.iter_raw()))
