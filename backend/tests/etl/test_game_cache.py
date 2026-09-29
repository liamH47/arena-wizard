from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from arena_wizard.domain.sets import EventType
from arena_wizard.etl import game_cache
from arena_wizard.etl.game_cache import (
    cache_dir,
    count_bytes,
    counts_from_json,
    counts_path,
    counts_to_json,
    file_path,
    load_file,
    read_cached,
)
from arena_wizard.sources.http import SourceError
from arena_wizard.sources.seventeenlands_files import public_file_url
from tests.conftest import ChunkedBody, FakeClock, make_context
from tests.seventeenlands_fixture import DAY1, file_bytes


class Bucket:
    """The 17Lands S3 bucket for one file, with a settable ETag, counting downloads."""

    def __init__(self, body: bytes, etag: str = '"v1"') -> None:
        self.body = body
        self.etag = etag
        self.gets = 0
        self.status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        assert str(request.url) == public_file_url("SOS", EventType.SEALED)
        if self.status != 200:
            return httpx.Response(self.status)
        headers = {"ETag": self.etag}
        if request.method == "HEAD":
            return httpx.Response(200, headers=headers)
        self.gets += 1
        return httpx.Response(200, headers=headers, stream=ChunkedBody(self.body))


def _load(bucket: Bucket, clock: FakeClock, root: Path):  # type: ignore[no-untyped-def]
    return load_file(make_context(bucket.handle, clock), "SOS", EventType.SEALED, root)


def test_the_first_load_downloads_counts_and_caches(tmp_path: Path, clock: FakeClock) -> None:
    bucket = Bucket(file_bytes())
    cached, status = _load(bucket, clock, tmp_path)
    assert status == "downloaded" and bucket.gets == 1
    assert cached.sha256 == hashlib.sha256(file_bytes()).hexdigest()
    assert cached.daily.cards[DAY1]["Alpha"].games_gih == 1
    assert file_path(tmp_path, "SOS", EventType.SEALED).read_bytes() == file_bytes()
    assert read_cached("SOS", EventType.SEALED, tmp_path) == cached


def test_an_unchanged_etag_with_the_file_intact_skips_the_download(
    tmp_path: Path, clock: FakeClock
) -> None:
    bucket = Bucket(file_bytes())
    first, _ = _load(bucket, clock, tmp_path)
    again, status = _load(bucket, clock, tmp_path)
    assert status == "unchanged" and bucket.gets == 1 and again == first


def test_a_reuploaded_file_is_downloaded_again(tmp_path: Path, clock: FakeClock) -> None:
    bucket = Bucket(file_bytes())
    _load(bucket, clock, tmp_path)
    bucket.etag = '"v2"'
    second, status = _load(bucket, clock, tmp_path)
    assert status == "downloaded" and bucket.gets == 2 and second.etag == '"v2"'
    assert not list((tmp_path / "17lands").glob("*.tmp"))


def test_a_deleted_file_is_downloaded_again_even_with_the_same_etag(
    tmp_path: Path, clock: FakeClock
) -> None:
    bucket = Bucket(file_bytes())
    _load(bucket, clock, tmp_path)
    file_path(tmp_path, "SOS", EventType.SEALED).unlink()
    _, status = _load(bucket, clock, tmp_path)
    assert status == "downloaded" and bucket.gets == 2


def test_a_corrupted_file_is_downloaded_again(tmp_path: Path, clock: FakeClock) -> None:
    bucket = Bucket(file_bytes())
    _load(bucket, clock, tmp_path)
    file_path(tmp_path, "SOS", EventType.SEALED).write_bytes(b"truncated")
    _, status = _load(bucket, clock, tmp_path)
    assert status == "downloaded" and bucket.gets == 2


def test_counts_from_older_rules_are_recounted_without_downloading(
    tmp_path: Path, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    bucket = Bucket(file_bytes())
    _load(bucket, clock, tmp_path)
    monkeypatch.setattr(game_cache, "COUNTS_VERSION", 2)
    recounted, status = _load(bucket, clock, tmp_path)
    assert status == "recounted" and bucket.gets == 1
    assert recounted.counts_version == 2
    assert read_cached("SOS", EventType.SEALED, tmp_path) == recounted


@pytest.mark.parametrize("status", [403, 500])
def test_a_missing_or_failing_file_raises(tmp_path: Path, clock: FakeClock, status: int) -> None:
    bucket = Bucket(file_bytes())
    bucket.status = status
    with pytest.raises(SourceError, match=str(status)):
        _load(bucket, clock, tmp_path)


def test_a_download_that_fails_after_the_head_raises(tmp_path: Path, clock: FakeClock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.method == "HEAD" else 503)

    with pytest.raises(SourceError, match="503"):
        load_file(make_context(handler, clock), "SOS", EventType.SEALED, tmp_path)


def test_counts_round_trip_and_an_incompatible_cache_reads_as_missing(
    tmp_path: Path, clock: FakeClock
) -> None:
    cached, _ = _load(Bucket(file_bytes()), clock, tmp_path)
    assert counts_from_json(counts_to_json(cached)) == cached
    document = json.loads(counts_to_json(cached))
    document["format_version"] = 99
    assert counts_from_json(json.dumps(document)) is None
    counts_path(tmp_path, "SOS", EventType.SEALED).write_text(json.dumps(document), "utf-8")
    assert read_cached("SOS", EventType.SEALED, tmp_path) is None


def test_count_bytes_counts_the_gzipped_file() -> None:
    assert count_bytes(file_bytes()).cards[DAY1]["Alpha"].games_played == 2


def test_nothing_cached_is_none(tmp_path: Path) -> None:
    assert read_cached("SOS", EventType.SEALED, tmp_path) is None
    assert counts_path(tmp_path, "SOS", EventType.SEALED).name == "SOS.Sealed.counts.json"


def test_the_cache_directory_follows_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARENA_WIZARD_CACHE_DIR", str(tmp_path))
    assert cache_dir() == tmp_path
    monkeypatch.delenv("ARENA_WIZARD_CACHE_DIR")
    assert cache_dir() == Path.home() / ".cache" / "arena-wizard"
