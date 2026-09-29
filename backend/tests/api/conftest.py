from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.database import dispose_all


@pytest.fixture(autouse=True)
def _dispose_app_engines() -> Iterator[None]:
    """Close every database engine an app factory opened during the test."""
    yield
    dispose_all()
