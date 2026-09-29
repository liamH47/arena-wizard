"""Request-body rules the API enforces before anything touches the database."""

from __future__ import annotations

import pytest

from arena_wizard.api.schemas import storable, web_link


def test_ordinary_text_including_accents_is_storable() -> None:
    assert storable("1 D\u00e1in Ironfoot (HOB) 1") == "1 D\u00e1in Ironfoot (HOB) 1"


@pytest.mark.parametrize(
    ("text", "message"),
    [("a\x00b", "NUL"), ("a\ud800b", "not valid Unicode")],
)
def test_text_postgres_cannot_store_is_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        storable(text)


@pytest.mark.parametrize("url", [None, "https://example.com/x", "HTTP://example.com"])
def test_web_links_are_accepted(url: str | None) -> None:
    assert web_link(url) == url


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///etc/passwd", "example.com"])
def test_anything_but_a_web_link_is_refused(url: str) -> None:
    with pytest.raises(ValueError, match="http"):
        web_link(url)
